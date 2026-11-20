"""Security alerts: emails the admins (ADMIN_EMAILS) when the security log shows something a person must look at.

hub.security.audit() passes every event to check(). docs/operations/SECURITY-ALERTS.md says what to do for each alert.
"""

import logging
import time

from django.core.cache import cache
from django.core.mail import mail_admins

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


def count(key, window):
    """Count one more for `key` in its current window. Returns how many so far in that window."""
    # shortcut: fixed windows, so a burst split across two windows may count in neither; fine for a tripwire.
    # The count is shared by every gunicorn worker only when settings.CACHES is a shared cache (the database).
    now = time.time()
    seen, until = cache.get(key) or (0, 0)
    if until <= now:
        seen, until = 0, now + WINDOWS[window]
    cache.set(key, (seen + 1, until), until - now)
    return seen + 1


def check(event, details):
    """Email the admins if this event makes its alert's count reach the threshold."""
    if event not in RULES:
        return
    alert, most, window, per_person = RULES[event]
    who = details.get("user_id") if per_person else ""
    if per_person and not who:
        return  # nobody signed in, e.g. a limit on sign-in tries: the failed sign-in alert covers those
    if most > 1 and count(f"alert:{alert}:{who}".replace(" ", "_"), window) != most:
        return
    lines = [f"{alert}."]
    if most > 1:
        lines.append(f"{most} times within {window}" + (f", all by {details.get('user')}." if per_person else "."))
    lines += ["", "The last one, from the security log:", f"event: {event}"]
    lines += [f"{key}: {value}" for key, value in details.items()]
    lines += ["", f'What to do: see "{alert}" in docs/operations/SECURITY-ALERTS.md.']
    log.warning("security_alert", extra={"details": {"alert": alert, "trigger": event}})
    # A broken mail relay must not break the sign-in or the admin save that set this off; the log line above stays.
    mail_admins(f"Staff hub: {alert.lower()}", "\n".join(lines), fail_silently=True)
