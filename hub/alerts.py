"""Security alerts: emails the admins (ADMIN_EMAILS) when the security log shows something a person must look at.

hub.security.audit() passes every event to check(). This module also logs admin rights given or taken away.
docs/operations/SECURITY-ALERTS.md says what to do for each alert.
"""

import json
import logging
import time

from django.conf import settings
from django.core import checks
from django.core.cache import cache
from django.core.mail import mail_admins
from django.db import transaction
from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver

log = logging.getLogger("hub.security")

WINDOWS = {"15 minutes": 15 * 60, "an hour": 60 * 60, "a day": 24 * 60 * 60}

# Security log event: (alert, how many, within, counted per person). Events sharing an alert share one count.
# One email when the count is reached, then none until the window ends, so an attack can't flood the mailbox.
RULES = {
    "admin_rights_changed": ("Admin rights changed", 1, None, False),
    "sign_in_failed": ("Many failed sign-ins", 10, "15 minutes", False),
    "sign_in_rejected": ("Many failed sign-ins", 10, "15 minutes", False),
    "rate_limited": ("One person keeps hitting the limits", 5, "an hour", True),
    "file_downloaded": ("One person is downloading many files", 100, "a day", True),
    "data_exported": ("One person keeps exporting their data", 3, "a day", True),
}


def reached(key, most, seconds):
    """Count one more for `key` in this window. True once per window, when the count gets to `most`."""
    # Windows follow the clock: 15 minutes means :00 to :15 and so on, a day runs from midnight UTC.
    # shortcut: a burst split across two windows may count in neither; fine for a tripwire.
    # The count is shared by every gunicorn worker only when settings.CACHES is a shared cache (the database).
    key = f"{key}:{int(time.time() // seconds)}"
    seen = cache.get(key, 0) + 1
    cache.set(key, seen, seconds)
    # Two events at the same moment may count as one, so test with >=. cache.add lets only one of them send the email.
    return seen >= most and cache.add(f"{key}:sent", True, seconds)


def check(event, details):
    """Email the admins if this event makes its alert's count reach the threshold."""
    if event not in RULES:
        return
    alert, most, window, per_person = RULES[event]
    who = details.get("user_id") if per_person else ""
    if per_person and not who:
        return  # nobody signed in, e.g. a limit on sign-in tries: the failed sign-in alert covers those
    if most > 1 and not reached(f"alert:{alert}:{who}".replace(" ", "_"), most, WINDOWS[window]):
        return
    # As JSON, so a typed sign-in name can't add lines of its own to the email.
    shown = {key: json.dumps(value, default=str, ensure_ascii=False) for key, value in details.items()}
    lines = [f"{alert}."]
    if most > 1:
        lines.append(f"{most} times within {window}" + (f", all by {shown.get('user')}." if per_person else "."))
    lines += ["", "The last one, from the security log:", f"event: {event}"]
    lines += [f"{key}: {value}" for key, value in shown.items()]
    lines += ["", f'What to do: see "{alert}" in docs/operations/SECURITY-ALERTS.md.']
    log.warning("security_alert", extra={"details": {"alert": alert, "trigger": event}})
    # A broken mail relay must not break the sign-in or the admin save that set this off; the log line above stays.
    # shortcut: sent inside the request, so a stalled relay holds it for up to settings.EMAIL_TIMEOUT; move this to
    # the scheduler if alerts ever become frequent.
    mail_admins(f"Staff hub: {alert.lower()}", "\n".join(lines), fail_silently=True)


@checks.register(checks.Tags.security, deploy=True)
def admin_emails_set(app_configs, **kwargs):
    if settings.ADMINS:
        return []
    # Info, not Warning: CI runs check --deploy --fail-level WARNING without any mail settings.
    return [checks.Info(
        "ADMIN_EMAILS is empty, so security alerts and server error alerts reach nobody.",
        hint="Set ADMIN_EMAILS in .env to IT's alert mailbox (docs/operations/SECURITY-ALERTS.md).", id="hub.I001",
    )]


# --- Admin rights ------------------------------------------------------------------
# Caught at the model, so a change made on the server (shell, createsuperuser) is logged as well as one in the admin.
# Admin > Log entries shows who made a change in the admin. update(), bulk_update() and SQL skip these signals:
# the quarterly access review is the backstop for those.

ADMIN_FLAGS = {"is_staff": "staff status (opens the admin)", "is_superuser": "superuser (every permission)"}
WATCHED = [*ADMIN_FLAGS, "is_active", "password"]


def _name(obj):
    return getattr(obj, "email", "") or str(obj)


def _rights_changed(target, change):
    from .security import audit  # here: hub.security imports this module

    target = _name(target)
    # Logged once the save is committed, so a form that fails half-way can't report a change that never happened.
    transaction.on_commit(lambda: audit("admin_rights_changed", level=logging.WARNING, target=target, change=change))


def _has_rights(user):
    return user.is_staff or user.is_superuser or user.groups.exists() or user.user_permissions.exists()


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def _admin_flags_changed(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and not set(WATCHED) & set(update_fields):
        return  # e.g. last_login on every sign-in
    before = sender.objects.filter(pk=instance.pk).values(*WATCHED).first() if instance.pk else None
    for flag, label in ADMIN_FLAGS.items():
        now = bool(getattr(instance, flag))
        if now != bool(before and before[flag]):
            _rights_changed(instance, f"{'given' if now else 'lost'} {label}")
    if before is None:
        return
    # Waking a dormant admin account, or giving it a password, is a way back in that the flags above don't show.
    woken = instance.is_active and not before["is_active"]
    new_password = instance.password != before["password"]
    if (woken or new_password) and _has_rights(instance):
        if woken:
            _rights_changed(instance, "admin account switched back on")
        if new_password:
            _rights_changed(instance, "admin account given a new password")


def _roles_changed(sender, instance, action, model, pk_set, **kwargs):
    if action in ("post_add", "post_remove", "post_clear"):
        changed = "all" if pk_set is None else ", ".join(map(_name, model.objects.filter(pk__in=pk_set)))
        _rights_changed(instance, f"{model._meta.verbose_name} {'added' if action == 'post_add' else 'removed'}: {changed}")


# The tables linking people to roles (groups) and permissions, and roles to permissions. Named as strings
# because this module loads with the logging setup (through hub.security), before the models exist.
for _link in (f"{settings.AUTH_USER_MODEL}_groups", f"{settings.AUTH_USER_MODEL}_user_permissions", "auth.Group_permissions"):
    m2m_changed.connect(_roles_changed, sender=_link)
