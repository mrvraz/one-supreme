"""What chat plugs into the shared pages. Registered in apps.py (see hub/plugins.py for what each hook does)."""

import os
from datetime import timedelta

from django.conf import settings
from django.db.models import Exists, F, Q

from hub.models import DELETED_KEEP_DAYS, Report

from .models import Membership, Message, unread


def unread_chats(user):
    """The red number on the Chat tab: chats with something new, leaving out muted ones."""
    return Membership.objects.filter(user=user, muted=False).filter(Exists(unread())).count()


def can_open_picture(user, name):
    pictures = Message.objects.filter(image=name)
    # One filter() call, so both conditions apply to the same membership: sent while this person was in the chat.
    mine = pictures.filter(conversation__memberships__user=user, conversation__memberships__joined_at__lte=F("created_at"))
    if mine.filter(deleted_at__isnull=True).exists():
        return True
    # Moderators may open the pictures of someone who has been reported, so they can judge a chat report.
    return user.has_perm("hub.change_report") and pictures.filter(sender__reports_about__isnull=False).exists()


def export(user):
    mine = Message.objects.filter(sender=user).select_related("conversation").prefetch_related("conversation__memberships__user")
    data = [
        {
            "conversation": m.conversation.label_for(user), "text": m.body, "time": m.created_at,
            "picture": os.path.basename(m.image.name), "deleted_at": m.deleted_at,
        }
        for m in mine
    ]
    return "chat", data, [m.image.path for m in mine if m.image]


def purge(now):
    old = Q(deleted_at__lt=now - timedelta(days=DELETED_KEEP_DAYS))
    keep_days = getattr(settings, "CHAT_RETENTION_DAYS", 0)
    if keep_days > 0:
        old |= Q(created_at__lt=now - timedelta(days=keep_days))
    # Messages from someone under an open report stay until a moderator closes it: they may be evidence.
    reported = Report.objects.filter(resolved_at__isnull=True, person__isnull=False).values("person")
    doomed = Message.objects.filter(old).exclude(sender__in=reported)
    removed = 0
    # In batches: delete() loads every message to remove its picture (post_delete), and the first run after
    # switching on CHAT_RETENTION_DAYS can find years of them. Nothing else points at a message, so the total
    # is the number of messages.
    while batch := list(doomed.values_list("pk", flat=True)[:1000]):
        removed += Message.objects.filter(pk__in=batch).delete()[0]
    return "chat messages", removed
