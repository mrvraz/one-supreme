"""What happens when a post goes live: who is told, and who was mentioned."""

import re

from django.utils import timezone

from .models import Post, User, notify


def find_mentions(text):
    """Active colleagues whose "@Full Name" appears in the text.

    shortcut: two colleagues with exactly the same name are both mentioned; add a picker that stores the
    chosen person if that becomes a real problem.
    """
    if "@" not in (text or ""):
        return []
    # (?!\w): "@Ann Lee" must not also match inside "@Ann Leeson".
    return [p for p in User.objects.filter(is_active=True) if str(p) and re.search(rf"@{re.escape(str(p))}(?!\w)", text)]


def post_audience(post):
    """The active people a post is for."""
    people = User.objects.filter(is_active=True)
    if post.community_id:
        return people.filter(communities=post.community_id)
    audiences = list(post.audiences.values_list("pk", flat=True))
    return people.filter(communities__in=audiences).distinct() if audiences else people


def announce(post):
    """Tell people about a post that is now live. Safe to call twice: only the first call does anything."""
    if not post.is_live:
        return  # checked before claiming, so a post that isn't live yet is still announced when it is
    if not Post.objects.filter(pk=post.pk, notified_at__isnull=True).update(notified_at=timezone.now()):
        return
    author, url = post.author, post.get_absolute_url()
    if post.kind == Post.NEWS:
        notify(post_audience(post), author, f"News: {post.title}", url, category="news")
    elif post.is_announcement:
        notify(post_audience(post), author, f"{author} posted an announcement", url, category="news")
    elif post.kind == Post.POLL:
        notify(post_audience(post), author, f"{author} asked: {post.body[:120]}", url, category="polls")
    elif post.kind == Post.UPDATE and post.community_id:
        # Only reaches members who switched on "New posts in my groups and teams".
        notify(post_audience(post), author, f"{author} posted in {post.community}", url, category="posts")
    notify(post.mentions.filter(is_active=True), author, f"{author} mentioned you", url, category="mentions")


def set_mentions(item, old=()):
    """Store who is mentioned in a post or comment. Returns the people newly mentioned."""
    people = find_mentions(item.body)
    item.mentions.set(people)
    return [person for person in people if person not in old]
