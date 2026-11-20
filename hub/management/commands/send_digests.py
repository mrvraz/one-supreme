from collections import defaultdict

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from hub.models import Notification


class Command(BaseCommand):
    help = "Email each person a summary of notifications they haven't read or been emailed about yet. Run daily."

    def handle(self, *args, **options):
        pending = Notification.objects.filter(
            read_at__isnull=True,
            emailed_at__isnull=True,
            recipient__is_active=True,
            recipient__email_digest=True,
        ).select_related("recipient")
        by_person = defaultdict(list)
        for item in pending:
            by_person[item.recipient].append(item)

        sent = failed = 0
        now = timezone.now()
        connection = get_connection()  # one mail-server session for everyone, not a new one per person
        for person, all_items in by_person.items():
            if person.dnd_on or (person.dnd_weekends and timezone.localtime(now).weekday() >= 5):
                continue  # they asked for quiet: it all goes in the next digest
            items = [n for n in all_items if person.wants(n.category, "email")]
            skipped = [n.pk for n in all_items if n not in items]
            # Types they don't want by email count as handled, so they never pile up.
            Notification.objects.filter(pk__in=skipped).update(emailed_at=now)
            if not items:
                continue
            body = render_to_string(
                "hub/email/digest.txt",
                {"user": person, "items": items[:20], "SITE_NAME": settings.SITE_NAME, "SITE_URL": settings.SITE_URL},
            )
            subject = f"{len(items)} new update{'s' if len(items) != 1 else ''} on {settings.SITE_NAME}"
            try:
                connection.open()  # does nothing while the session is still open
                send_mail(subject, body, None, [person.email], connection=connection)
            except Exception as exc:  # one bad address or SMTP hiccup must not stop everyone else's email
                connection.close()  # the next person starts a fresh session
                failed += 1
                self.stderr.write(f"Could not email {person.email}: {exc}")
                continue
            # Marked only after a successful send, so failures are retried on the next run.
            Notification.objects.filter(pk__in=[n.pk for n in items]).update(emailed_at=timezone.now())
            sent += 1
        connection.close()
        self.stdout.write(f"Sent {sent} digest(s), {failed} failed.")
