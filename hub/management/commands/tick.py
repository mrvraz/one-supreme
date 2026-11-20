from django.core.management.base import BaseCommand

from hub import push, tasks


class Command(BaseCommand):
    help = "The every-minute jobs: publish scheduled posts, send event reminders, send push notifications."

    def handle(self, *args, **options):
        published = tasks.publish_due()
        reminded = tasks.send_reminders()
        pushed = push.send_pending()
        if published or reminded or pushed:
            self.stdout.write(f"Published {published}, reminded {reminded}, pushed {pushed}.")
