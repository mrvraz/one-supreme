"""Runs the hub's background jobs, forever. Started by the `scheduler` service in docker-compose.

Every minute: scheduled posts, event reminders and push notifications ("tick").
Every 15 minutes: the leaver check, quietly (a failure is logged; the daily run at 05:00 also emails it).
Every hour: the disk-space check. Every day at 05:00 UTC: the email digest, the leaver check and the clean-up.
"""

import logging
import time
from datetime import datetime, timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections

log = logging.getLogger("hub.scheduler")


def run(name, *args):
    """Run one job. A failing job is logged and never stops the others."""
    close_old_connections()
    try:
        call_command(name, *args)
    except Exception:
        log.exception("Scheduled job %s failed", name)


class Command(BaseCommand):
    help = "Run the background jobs forever: every minute, every hour and once a day."

    def handle(self, *args, **options):
        self.stdout.write("Scheduler started.")
        last_hour = last_day = last_quarter = None
        while True:
            now = datetime.now(timezone.utc)
            run("tick")
            # Leavers are switched off, and so signed out everywhere, within 15 minutes of leaving the directory.
            if (now.hour, now.minute // 15) != last_quarter:
                last_quarter = (now.hour, now.minute // 15)
                run("sync_directory", "--no-email")
            # Keyed on the hour having changed, not on minute 0: a slow tick at 04:59 must not skip a whole day.
            if now.hour != last_hour:
                last_hour = now.hour
                run("check_disk")
            # shortcut: a restart between 05:00 and 06:00 runs the daily jobs a second time; all three are safe
            # to repeat (a digest only sends what is still unsent). Store the last run day if that ever matters.
            if now.hour == 5 and now.date() != last_day:
                last_day = now.date()
                for job in ("send_digests", "sync_directory", "purge"):
                    run(job)
            time.sleep(60 - time.time() % 60)  # wake at the start of the next minute
