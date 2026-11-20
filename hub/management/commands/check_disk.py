import logging

from django.core.mail import mail_admins
from django.core.management.base import BaseCommand

from hub.media import MIN_FREE_DISK, disk_free_share
from hub.security import audit

WARN_BELOW = 0.15


class Command(BaseCommand):
    help = "Email the admins (ADMIN_EMAILS) when the disk holding uploads and the database is filling up. Run hourly."

    def handle(self, *args, **options):
        free = disk_free_share()
        if free >= WARN_BELOW:
            self.stdout.write(f"Disk OK: {free:.0%} free.")
            return
        paused = free < MIN_FREE_DISK
        audit("disk_space_low", level=logging.ERROR if paused else logging.WARNING, free_share=round(free, 3))
        message = f"The staff hub's disk is {1 - free:.0%} full ({free:.0%} free)."
        if paused:
            message += " Uploads are paused until space is freed."
        mail_admins("Staff hub: disk space low", message + " Add disk space or remove old files.")
        self.stdout.write(message)
