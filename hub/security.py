"""Security plumbing: the audit log, browser security headers, the house-rules gate and activity limits."""

import json
import logging
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.mail import mail_admins
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

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


def record_change(user, obj, message, deletion=False):
    """Add a line to the admin audit log (Admin > Log entries)."""
    from django.contrib.admin.models import CHANGE, DELETION, LogEntry  # here: logging setup loads this module early

    LogEntry.objects.log_actions(user.pk, [obj], DELETION if deletion else CHANGE, message, single_object=True)


@receiver(user_logged_in)
def _signed_in(sender, request, user, **kwargs):
    audit("sign_in", request, user)
    if settings.OIDC_ENABLED and getattr(user, "backend", "") == "hub.auth.PasswordBackend":
        # A password sign-in while single sign-on is on: the break-glass account, which skips Entra's MFA.
        mail_admins(
            "Staff hub: break-glass sign-in",
            f"{user.email} signed in with a password from {client_ip(request)}. If nobody planned this, set "
            "ALLOW_PASSWORD_LOGIN=0, restart the hub and change that account's password.",
            fail_silently=True,  # break-glass is for when things are broken: a dead mail server must not block it
        )


@receiver(user_logged_out)
def _signed_out(sender, request, user, **kwargs):
    if user is not None:
        audit("sign_out", request, user)


@receiver(user_login_failed)
def _sign_in_failed(sender, credentials, request=None, **kwargs):
    audit("sign_in_failed", request, level=logging.WARNING, username=credentials.get("username", ""))


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
