"""Web Push: sends the notifications people asked to get on their phone or browser.

The message is encrypted for the one device it goes to (RFC 8291), so the push services of Apple, Google
and Mozilla pass it on without being able to read it. The server needs outbound HTTPS to those services.
"""

import base64
import json
import logging
import os
from datetime import timedelta
from urllib.parse import urlsplit

import http_ece
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from py_vapid import Vapid02

from .models import Notification
from .security import audit

FRESH = timedelta(minutes=10)  # older notifications are not pushed: a late buzz is worse than none


def _b64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def send_to(subscription, payload, session=requests):
    """Encrypt and send one push message. Returns the push service's HTTP status."""
    body = http_ece.encrypt(
        json.dumps(payload).encode(),
        salt=os.urandom(16),
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=_b64(subscription.p256dh),
        auth_secret=_b64(subscription.auth),
        version="aes128gcm",
    )
    target = urlsplit(subscription.endpoint)
    headers = Vapid02.from_raw(settings.VAPID_PRIVATE_KEY.encode()).sign(
        {"aud": f"{target.scheme}://{target.netloc}", "sub": settings.VAPID_CONTACT}
    )
    headers.update({"Content-Encoding": "aes128gcm", "TTL": "3600"})
    return session.post(subscription.endpoint, data=body, headers=headers, timeout=(3, 5)).status_code


def send_pending(now=None):
    """Push every fresh notification that hasn't been pushed yet. Returns how many messages were sent."""
    if not settings.VAPID_PRIVATE_KEY:
        return 0
    now = now or timezone.now()
    waiting = Notification.objects.filter(pushed_at__isnull=True)
    waiting.filter(created_at__lt=now - FRESH).update(pushed_at=now)  # e.g. the server was down: skip, don't buzz late
    sent = 0
    session = requests.Session()  # one connection per push service, not one per message
    # Push services that didn't answer this run. Skipped until the next run: pushes are sent inside the scheduler's
    # tick, so 150 phones behind a blocked service would otherwise hold up event reminders for many minutes.
    unreachable = set()
    for item in waiting.select_related("recipient"):
        # Marked first: if this crashes half-way, nobody gets the same buzz twice.
        if not Notification.objects.filter(pk=item.pk, pushed_at__isnull=True).update(pushed_at=now):
            continue
        person = item.recipient
        if item.read_at or not person.is_active or person.dnd_active(now) or not person.wants(item.category, "push"):
            continue
        payload = {
            "title": settings.SITE_NAME,
            "body": item.message if person.push_privacy == "all" else "You have a new notification",
            "url": reverse("notification_open", args=[item.pk]),
            "tag": f"n{item.pk}",
        }
        for subscription in person.push_subscriptions.all():
            service = urlsplit(subscription.endpoint).netloc
            if service in unreachable:
                continue
            try:
                status = send_to(subscription, payload, session)
            except (requests.ConnectionError, requests.Timeout) as exc:
                unreachable.add(service)
                audit("push_failed", level=logging.WARNING, error=str(exc)[:200])
                continue
            except (requests.RequestException, ValueError) as exc:
                audit("push_failed", level=logging.WARNING, error=str(exc)[:200])
                continue
            if status in (404, 410):
                subscription.delete()  # that browser or phone has unsubscribed
            elif status >= 400:
                audit("push_failed", level=logging.WARNING, status=status)
            else:
                sent += 1
    return sent
