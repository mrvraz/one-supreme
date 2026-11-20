"""Jobs that run every minute: scheduled posts going live, event reminders, and push notifications."""

from datetime import timedelta

from django.utils import timezone

from .models import REMINDER_CHOICES, RSVP, Post, ReminderSent, notify
from .publishing import announce

LATE = timedelta(minutes=15)  # a reminder that can't go out within 15 minutes of its time is skipped, not sent late


def publish_due(now=None):
    """Tell people about scheduled posts whose time has come. Returns how many went live."""
    now = now or timezone.now()
    due = Post.objects.filter(notified_at__isnull=True, is_draft=False, is_hidden=False, deleted_at__isnull=True, created_at__lte=now)
    count = 0
    for post in due:
        announce(post)
        count += 1
    return count


def _starts_in(minutes):
    if minutes == 0:
        return "is starting now"
    label = dict(REMINDER_CHOICES).get(minutes, f"{minutes} minutes before")
    return "starts in " + label.removesuffix(" before")


def send_reminders(now=None):
    """Remind people about events they're going to (or might go to), at the times they chose."""
    now = now or timezone.now()
    soon = RSVP.objects.filter(
        status__in=[RSVP.Status.GOING, RSVP.Status.MAYBE],
        user__is_active=True,
        event__starts_at__gt=now - LATE,
        event__starts_at__lte=now + timedelta(days=1) + LATE,
    ).select_related("event", "user")
    sent = 0
    for rsvp in soon:
        for minutes in rsvp.reminder_minutes():
            due = rsvp.event.starts_at - timedelta(minutes=minutes)
            if not due <= now < due + LATE:
                continue
            _, first_time = ReminderSent.objects.get_or_create(rsvp=rsvp, minutes=minutes)
            if first_time:
                notify([rsvp.user], None, f"Reminder: {rsvp.event.title} {_starts_in(minutes)}", rsvp.event.get_absolute_url(), category="events")
                sent += 1
    return sent
