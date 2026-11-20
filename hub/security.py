"""Security plumbing: the audit log, browser security headers, the house-rules gate and activity limits."""

import json
import logging
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db import transaction
from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from . import alerts

log = logging.getLogger("hub.security")


# --- Audit log ---------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so Supreme's security monitoring (SIEM) can read the log as it is."""

    def format(self, record):
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "details", {}),
        }
        return json.dumps(entry, default=str)


def client_ip(request):
    # nginx sets X-Real-IP from the address Supreme's proxy vouches for; browsers can't fake it.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def audit(event, request=None, user=None, level=logging.INFO, **details):
    if request is not None:
        user = user or getattr(request, "user", None)
        details.update(ip=client_ip(request), path=request.path)
    if user is not None and user.is_authenticated:
        details.update(user=user.email, user_id=user.pk)
    log.log(level, event, extra={"details": details})
    alerts.check(event, details)


def record_change(user, obj, message, deletion=False):
    """Add a line to the admin audit log (Admin > Log entries)."""
    from django.contrib.admin.models import CHANGE, DELETION, LogEntry  # here: logging setup loads this module early

    LogEntry.objects.log_actions(user.pk, [obj], DELETION if deletion else CHANGE, message, single_object=True)


@receiver(user_logged_in)
def _signed_in(sender, request, user, **kwargs):
    audit("sign_in", request, user)


@receiver(user_logged_out)
def _signed_out(sender, request, user, **kwargs):
    if user is not None:
        audit("sign_out", request, user)


@receiver(user_login_failed)
def _sign_in_failed(sender, credentials, request=None, **kwargs):
    audit("sign_in_failed", request, level=logging.WARNING, username=credentials.get("username", ""))


# --- Admin rights ------------------------------------------------------------------
# Caught at the model, so a change made on the server (shell, createsuperuser) is logged as well as one in the admin.
# Admin > Log entries shows who made a change in the admin.

ADMIN_FLAGS = {"is_staff": "staff status (opens the admin)", "is_superuser": "superuser (every permission)"}


def _name(obj):
    return getattr(obj, "email", "") or str(obj)


def _rights_changed(target, change):
    # Logged once the save is committed, so a form that fails half-way can't report a change that never happened.
    target = _name(target)
    transaction.on_commit(lambda: audit("admin_rights_changed", level=logging.WARNING, target=target, change=change))


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def _admin_flags_changed(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and not ADMIN_FLAGS.keys() & set(update_fields):
        return  # e.g. last_login on every sign-in
    before = sender.objects.filter(pk=instance.pk).values(*ADMIN_FLAGS).first() if instance.pk else None
    for flag, label in ADMIN_FLAGS.items():
        now = bool(getattr(instance, flag))
        if now != bool(before and before[flag]):
            _rights_changed(instance, f"{'given' if now else 'lost'} {label}")


def _roles_changed(sender, instance, action, model, pk_set, **kwargs):
    if action in ("post_add", "post_remove", "post_clear"):
        changed = "all" if pk_set is None else ", ".join(map(_name, model.objects.filter(pk__in=pk_set)))
        _rights_changed(instance, f"{model._meta.verbose_name} {'added' if action == 'post_add' else 'removed'}: {changed}")


# The tables linking people to roles (groups) and permissions, and roles to permissions. Named as strings
# because this module loads with the logging setup, before the models exist.
for _link in (f"{settings.AUTH_USER_MODEL}_groups", f"{settings.AUTH_USER_MODEL}_user_permissions", "auth.Group_permissions"):
    m2m_changed.connect(_roles_changed, sender=_link)


# --- Activity limits ---------------------------------------------------------------

# What one person may do: (how many, in what period). Generous for real use, tight enough to stop
# a hijacked account flooding everyone's feed or filling the server's disk.
LIMITS = {
    "post": (20, timedelta(hours=1)),
    "file": (60, timedelta(days=1)),
    "comment": (60, timedelta(hours=1)),
    "report": (10, timedelta(hours=1)),
    "event": (20, timedelta(hours=1)),
    "group": (10, timedelta(days=1)),
}
LIMIT_MESSAGE = "You've done that a lot in a short time. Please try again later."


def over_limit(kind, queryset, request=None, user=None, adding=1, field="created_at"):
    """True if adding `adding` more items would break the limit. queryset = this person's past items."""
    most, period = LIMITS[kind]
    recent = queryset.filter(**{f"{field}__gte": timezone.now() - period}).count()
    if recent + adding > most:
        audit("rate_limited", request, user, level=logging.WARNING, limit=kind)
        return True
    return False


# --- Middleware --------------------------------------------------------------------

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # Inline styles carry the brand colour and avatar sizes. Scripts, the real danger, stay locked to our own files.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "media-src 'self'",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


def security_headers(get_response):
    """Tell browsers to refuse scripts, frames and device access that we didn't put there."""

    def middleware(request):
        response = get_response(request)
        response.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        return response

    return middleware


def presence(get_response):
    """Note when each person was last active, at most once a minute, for the green "active" dot."""

    def middleware(request):
        user = request.user
        if user.is_authenticated:
            now = timezone.now()
            if not user.last_seen or (now - user.last_seen).total_seconds() > 60:
                get_user_model().objects.filter(pk=user.pk).update(last_seen=now)
                user.last_seen = now
        return get_response(request)

    return middleware


HOUSE_RULES_EXEMPT = ("/house-rules/", "/logout/", "/login/", "/oidc/", "/static/", "/media/", "/manifest", "/icon")


def house_rules(get_response):
    """Everyone accepts the current house rules (settings.POLICY_VERSION) before using the hub."""

    def middleware(request):
        user = request.user
        if (
            user.is_authenticated
            and user.policy_version != settings.POLICY_VERSION
            and not request.path.startswith(HOUSE_RULES_EXEMPT)
        ):
            return redirect(f"{reverse('house_rules')}?next={quote(request.get_full_path())}")
        return get_response(request)

    return middleware
