from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from hub.models import DELETED_KEEP_DAYS, Comment, Notification, Post, Report, User
from hub.security import audit


class Command(BaseCommand):
    help = "Remove data that has passed its retention period. Run daily."

    def handle(self, *args, **options):
        now = timezone.now()
        open_reports = Report.objects.filter(resolved_at__isnull=True)
        # Anything under an open report is kept until a moderator closes the report: it may be evidence.
        protected_posts = set(open_reports.values_list("post_id", flat=True)) | set(
            open_reports.values_list("comment__post_id", flat=True)
        )
        protected_comments = set(open_reports.values_list("comment_id", flat=True))

        deleted_cutoff = now - timedelta(days=DELETED_KEEP_DAYS)
        counts = {
            "deleted posts": self.remove(Post.objects.filter(deleted_at__lt=deleted_cutoff), protected_posts),
            "deleted comments": self.remove(Comment.objects.filter(deleted_at__lt=deleted_cutoff), protected_comments),
        }
        if settings.NOTIFICATION_RETENTION_DAYS:
            old = Notification.objects.filter(created_at__lt=now - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS))
            counts["old notifications"] = old.delete()[0]
        if settings.POST_RETENTION_DAYS:
            old = Post.objects.filter(created_at__lt=now - timedelta(days=settings.POST_RETENTION_DAYS))
            counts["posts past retention"] = self.remove(old, protected_posts)
        if settings.LEAVER_RETENTION_DAYS:
            cutoff = now - timedelta(days=settings.LEAVER_RETENTION_DAYS)
            # Counted from the day the account was switched off, not from their last sign-in.
            # Moderators (staff) stay: deleting an account also deletes its entries in the admin's moderation log.
            leavers = User.objects.filter(is_active=False, is_superuser=False, is_staff=False, deactivated_at__lt=cutoff)
            counts["leavers' accounts"] = 0
            for person in leavers:
                under_report = (
                    Post.objects.filter(author=person, pk__in=protected_posts).exists()
                    or Comment.objects.filter(author=person, pk__in=protected_comments).exists()
                    or open_reports.filter(person=person).exists()  # deleting them would delete the report too
                )
                if under_report:
                    continue
                audit("leaver_removed", user_id=person.pk, email=person.email)
                person.delete()  # their posts, comments and photos go with them (see hub.models post_delete)
                counts["leavers' accounts"] += 1

        from hub import plugins

        for purger in plugins.PURGERS:
            label, removed = purger(now)
            counts[label] = removed
        summary = ", ".join(f"{n} {what}" for what, n in counts.items())
        audit("retention_purge", summary=summary)
        self.stdout.write(f"Removed {summary}.")

    @staticmethod
    def remove(queryset, protected_ids):
        removed = 0
        for item in queryset.exclude(pk__in=[pk for pk in protected_ids if pk]):
            item.delete()  # one by one, so each photo and video file is deleted from disk too
            removed += 1
        return removed
