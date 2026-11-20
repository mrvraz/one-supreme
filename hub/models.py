from datetime import date, timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from . import richtext

# Notification types people can switch on or off: key -> (label, push by default, in the daily email by default).
NOTIFY_TYPES = {
    "comments": ("Comments and replies on my posts, and on posts I follow", True, False),
    "mentions": ("Someone mentions me", True, True),
    "reactions": ("Reactions to my posts and comments", False, False),
    "messages": ("New chat messages", True, False),
    "news": ("News and announcements", True, True),
    "posts": ("New posts in my groups and teams", False, False),
    "groups": ("Group invitations, requests and membership changes", True, False),
    "events": ("Event invitations, changes and reminders", True, False),
    "polls": ("New polls", True, False),
    "journeys": ("Journeys assigned to me", True, True),
    "general": ("Everything else", True, True),
}
# Types that only reach people who switched them on (they would be noise for everyone else).
OPT_IN_TYPES = {"posts"}

# Minutes before an event at which a reminder can be sent.
REMINDER_CHOICES = [
    (0, "When the event starts"),
    (5, "5 minutes before"),
    (10, "10 minutes before"),
    (15, "15 minutes before"),
    (30, "30 minutes before"),
    (60, "1 hour before"),
    (240, "4 hours before"),
    (1440, "1 day before"),
]


def default_reminders():
    return [1440, 60]


def matching(queryset, q, *fields):
    """Rows where every word of q appears in at least one of fields: the one search rule every section uses."""
    for word in q.split():
        match = Q()
        for field in fields:
            match |= Q(**{f"{field}__icontains": word})
        queryset = queryset.filter(match)
    return queryset


def next_occurrence(day, today=None):
    """The next date this day-and-month falls on (today counts). 29 February is marked on the 28th in other years."""
    today = today or timezone.localdate()
    for year in (today.year, today.year + 1):
        try:
            when = day.replace(year=year)
        except ValueError:
            when = date(year, 2, 28)
        if when >= today:
            return when


class User(AbstractUser):
    LOOKS = [("auto", "Match my device"), ("daylight", "Daylight"), ("daylight-dark", "Daylight Dark")]

    email = models.EmailField(unique=True)
    job_title = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=120, blank=True)
    bio = models.TextField(max_length=1000, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    cover = models.ImageField(upload_to="covers/people/", blank=True)
    pronouns = models.CharField(max_length=40, blank=True)
    languages = models.CharField("Spoken languages", max_length=200, blank=True)
    phone = models.CharField("Work phone", max_length=40, blank=True)
    # Opt-in: stored with the year 2000, shown as day and month only.
    birthday = models.DateField(null=True, blank=True)
    start_date = models.DateField("Started at the company", null=True, blank=True)
    share_email = models.BooleanField("Show my email address on my profile", default=True)
    show_presence = models.BooleanField("Show when I'm active", default=True)
    last_seen = models.DateTimeField(null=True, blank=True, editable=False)

    look = models.CharField(max_length=20, choices=LOOKS, default="auto")
    language = models.CharField("Translate posts into", max_length=8, default="en")
    email_digest = models.BooleanField("Daily email digest", default=True)
    notify_prefs = models.JSONField(default=dict, blank=True)  # {"news": {"push": false, "email": true}, ...}
    push_privacy = models.CharField(
        max_length=10, default="all", choices=[("all", "Show who and what"), ("hidden", "Only say there is something new")]
    )
    dnd_on = models.BooleanField("Do not disturb", default=False)
    dnd_from = models.TimeField("Quiet hours start", null=True, blank=True)
    dnd_to = models.TimeField("Quiet hours end", null=True, blank=True)
    dnd_weekends = models.BooleanField("Quiet all weekend", default=False)
    event_reminders = models.JSONField(default=default_reminders, blank=True)
    whats_new_seen_at = models.DateTimeField(null=True, blank=True, editable=False)

    policy_version = models.CharField(
        "Accepted house rules version", max_length=20, blank=True, help_text="Empty until they accept the house rules"
    )
    # The sign-in provider's permanent ID for this person (Microsoft "oid"), so an email change keeps the same account.
    sso_id = models.CharField("Single sign-on ID", max_length=255, unique=True, null=True, blank=True, editable=False)
    deactivated_at = models.DateTimeField(null=True, blank=True, editable=False, help_text="When the account was switched off")

    def __str__(self):
        return self.get_full_name() or self.email or self.username

    def save(self, *args, **kwargs):
        # Leaver retention counts from the day the account was switched off (see the purge command).
        self.deactivated_at = None if self.is_active else (self.deactivated_at or timezone.now())
        if kwargs.get("update_fields") is not None and "is_active" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "deactivated_at"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("profile", args=[self.pk])

    @property
    def initials(self):
        return "".join(part[0] for part in str(self).split()[:2]).upper()

    @property
    def avatar_hue(self):
        return (self.pk or 0) * 47 % 360

    @property
    def is_online(self):
        recently = timezone.now() - timedelta(minutes=5)
        return bool(self.show_presence and self.last_seen and self.last_seen > recently)

    def wants(self, category, channel):
        """Does this person want `category` notifications by `channel` ("push" or "email")?"""
        _label, push, email = NOTIFY_TYPES.get(category, NOTIFY_TYPES["general"])
        chosen = (self.notify_prefs or {}).get(category, {})
        return bool(chosen.get(channel, push if channel == "push" else email))

    def dnd_active(self, now=None):
        """True while this person has asked not to be disturbed: no push, no email. In-app alerts still collect."""
        if self.dnd_on:
            return True
        now = timezone.localtime(now)
        if self.dnd_weekends and now.weekday() >= 5:
            return True
        if self.dnd_from and self.dnd_to and self.dnd_from != self.dnd_to:
            clock = now.time()
            if self.dnd_from < self.dnd_to:
                return self.dnd_from <= clock < self.dnd_to
            return clock >= self.dnd_from or clock < self.dnd_to  # quiet hours that run past midnight
        return False


class Community(models.Model):
    """A set of colleagues. Either a group (a hobby or project, joined freely or by invitation)
    or a unit of the organisation (business unit, department, location or team, set by admins)."""

    GROUP, UNIT = "group", "unit"
    UNIT_TYPES = [("business", "Business unit"), ("department", "Department"), ("location", "Location"), ("team", "Team")]

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(max_length=1000, blank=True)
    kind = models.CharField(max_length=10, choices=[(GROUP, "Group"), (UNIT, "Organisation unit")], default=GROUP)
    unit_type = models.CharField(max_length=20, choices=UNIT_TYPES, blank=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    is_private = models.BooleanField("Private group", default=False, help_text="Only members see its posts and members. Others can ask to join.")
    cover = models.ImageField(upload_to="covers/groups/", blank=True)
    members = models.ManyToManyField(User, related_name="communities", blank=True)
    admins = models.ManyToManyField(User, related_name="communities_managed", blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        # "Groups" in the admin already means permission roles (e.g. Moderators), so say "social group" there.
        verbose_name = "group or unit"
        verbose_name_plural = "groups and units"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("community", args=[self.slug])

    @property
    def is_unit(self):
        return self.kind == self.UNIT

    @property
    def type_label(self):
        if self.is_unit:
            return self.get_unit_type_display() or "Organisation unit"
        return "Private group" if self.is_private else "Public group"

    def has_member(self, user):
        return self.members.filter(pk=user.pk).exists()

    def is_admin(self, user):
        return user.has_perm("hub.change_community") or self.admins.filter(pk=user.pk).exists()

    def can_view(self, user):
        """Public groups are open to all staff. Private groups and organisation units are for their members."""
        if self.kind == self.GROUP and not self.is_private:
            return True
        return self.has_member(user) or self.is_admin(user)

    def can_join(self, user):
        return self.kind == self.GROUP and not self.is_private


class GroupInvite(models.Model):
    """An invitation to a group, or someone's request to join a private group, waiting for an answer."""

    INVITE, REQUEST = "invite", "request"

    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="invites")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_invites")
    kind = models.CharField(max_length=10, choices=[(INVITE, "Invitation"), (REQUEST, "Request to join")])
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    answered_at = models.DateTimeField(null=True, blank=True)
    accepted = models.BooleanField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["community", "user"], condition=Q(answered_at__isnull=True), name="one_open_invite_per_person"
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.user} / {self.community}"


DELETED_KEEP_DAYS = 30


class ModeratedQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(is_hidden=False, deleted_at__isnull=True)


class Moderated(models.Model):
    """Posts and comments: moderators can hide them, and deleting keeps them for DELETED_KEEP_DAYS.

    The grace period means someone reported for harassment can't destroy the evidence before HR sees it.
    """

    is_hidden = models.BooleanField(default=False, help_text="Hidden by a moderator")
    deleted_at = models.DateTimeField(null=True, blank=True, help_text=f"Removed for good {DELETED_KEEP_DAYS} days later")
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    objects = ModeratedQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self, user):
        self.deleted_at, self.deleted_by = timezone.now(), user
        self.save(update_fields=["deleted_at", "deleted_by"])


class PostQuerySet(ModeratedQuerySet):
    def visible(self):
        """Live posts: not hidden, not deleted, not a draft, and past their publication time."""
        return super().visible().filter(is_draft=False, created_at__lte=timezone.now())

    def _audience(self, user, open_groups):
        # Subqueries, not joins: a join repeats each post once per audience, and the DISTINCT that undoes it
        # makes every count and page of posts compare whole rows.
        mine = user.communities.all()
        chosen = Post.audiences.through.objects.filter(post=OuterRef("pk"))
        allowed = Post.for_everyone() | Q(community__in=mine) | Exists(chosen.filter(community__in=mine)) | Q(author=user)
        if open_groups:
            allowed |= Q(community__kind=Community.GROUP, community__is_private=False)
        return self.filter(allowed)

    def counting(self, **counts):
        """Add how many rows of each queryset belong to each post: counting(comment_count=Comment.objects.visible()).

        Subqueries, so two counts don't multiply each other's rows the way two joined Count()s do.
        """
        def per_post(rows):
            return Coalesce(Subquery(rows.filter(post=OuterRef("pk")).order_by().values("post").annotate(n=Count("pk")).values("n")), 0)

        return self.annotate(**{name: per_post(rows) for name, rows in counts.items()})

    def in_feed_of(self, user):
        """What belongs in this person's feed: company-wide posts and posts for their groups and units."""
        return self._audience(user, open_groups=False)

    def viewable_by(self, user):
        """What this person may open: their feed, plus public groups they haven't joined. Moderators see everything."""
        if user.has_perm("hub.change_post"):
            return self
        return self._audience(user, open_groups=True)


class Post(Moderated):
    UPDATE, NEWS, POLL, EVENT = "update", "news", "poll", "event"
    KINDS = [(UPDATE, "Post"), (NEWS, "News"), (POLL, "Poll"), (EVENT, "Event")]

    kind = models.CharField(max_length=10, choices=KINDS, default=UPDATE, db_index=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="posts")
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, null=True, blank=True, related_name="posts", verbose_name="group"
    )
    # News can go to several groups and units at once. Empty (with no group above) means everyone.
    audiences = models.ManyToManyField(Community, blank=True, related_name="news")
    title = models.CharField(max_length=200, blank=True)
    cover = models.ImageField(upload_to="covers/news/", blank=True, db_index=True)  # looked up on every cover request
    body = models.TextField(max_length=20000, blank=True)
    mentions = models.ManyToManyField(User, blank=True, related_name="mentioned_in")
    is_announcement = models.BooleanField(default=False, help_text="Everyone is told about it")
    is_draft = models.BooleanField(default=False)
    requires_ack = models.BooleanField("Readers must confirm they've read it", default=False)
    pinned_at = models.DateTimeField(null=True, blank=True, db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    # When the post goes live. A time in the future makes it a scheduled post.
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    notified_at = models.DateTimeField(null=True, blank=True, editable=False, help_text="When people were told about it")
    event = models.OneToOneField("Event", on_delete=models.CASCADE, null=True, blank=True, related_name="feed_post")
    poll_closes_at = models.DateTimeField(null=True, blank=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        permissions = [("publish_news", "Can publish news"), ("view_insights", "Can view usage figures")]

    def __str__(self):
        return (self.title or self.body[:60] or f"Post {self.pk}").replace("\n", " ")

    @staticmethod
    def for_everyone():
        """Q for posts to the whole company: no group and no chosen audiences."""
        return Q(community__isnull=True) & ~Exists(Post.audiences.through.objects.filter(post=OuterRef("pk")))

    def get_absolute_url(self):
        return reverse("post_detail", args=[self.pk])

    @property
    def body_html(self):
        return richtext.render(self.body, self.mentions.all())

    @property
    def is_scheduled(self):
        return not self.is_draft and self.created_at > timezone.now()

    @property
    def is_live(self):
        return not (self.is_hidden or self.deleted_at or self.is_draft or self.is_scheduled)

    @property
    def poll_open(self):
        return self.poll_closes_at is None or self.poll_closes_at > timezone.now()

    def can_pin(self, user):
        if user.has_perm("hub.change_post"):
            return True
        return bool(self.community_id) and self.community.is_admin(user)

    def touch(self):
        """Mark fresh activity (a comment or reaction), for the feed's "recent activity" order."""
        Post.objects.filter(pk=self.pk).update(last_activity_at=timezone.now())


class Attachment(models.Model):
    IMAGE, VIDEO = "image", "video"

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="posts/%Y/%m/", db_index=True)  # looked up on every photo request
    kind = models.CharField(max_length=10, choices=[(IMAGE, "Image"), (VIDEO, "Video")])
    alt_text = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["pk"]


class PollOption(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=200)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return self.text


class PollVote(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="poll_votes")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="one_vote_per_person")]


class PostRead(models.Model):
    """Who has opened a news item, and who has confirmed reading one that asks for it."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="post_reads")
    read_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="one_read_per_person")]


class PostFollow(models.Model):
    """Someone asked to be told about new comments on a post that isn't theirs."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="follows")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="post_follows")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="one_follow_per_person")]


class Comment(Moderated):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    body = models.TextField(max_length=2000, blank=True)
    image = models.ImageField(upload_to="comments/%Y/%m/", blank=True, db_index=True)  # looked up on every picture request
    mentions = models.ManyToManyField(User, blank=True, related_name="mentioned_in_comments")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        # A post card's newest threads. Without it SQLite reads every top-level comment through the parent index.
        indexes = [models.Index(fields=["post", "parent", "created_at"])]

    def __str__(self):
        return self.body[:60] or "(picture)"

    @property
    def body_html(self):
        return richtext.render(self.body, self.mentions.all())

    def get_absolute_url(self):
        return self.post.get_absolute_url() + f"#comment-{self.pk}"


@receiver(post_delete, sender=Attachment)
def _delete_attachment_file(sender, instance, **kwargs):
    # Deleted posts must not leave their photos behind on disk.
    instance.file.delete(save=False)


@receiver(post_delete, sender=Post)
def _delete_post_cover(sender, instance, **kwargs):
    if instance.cover:
        instance.cover.delete(save=False)


@receiver(post_delete, sender=Comment)
def _delete_comment_image(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)


@receiver(post_delete, sender=Community)
def _delete_group_cover(sender, instance, **kwargs):
    instance.cover.delete(save=False)  # groups are deleted in the admin; their cover must not stay on disk


@receiver(post_delete, sender=User)
def _delete_profile_photos(sender, instance, **kwargs):
    # Leavers (the purge command) and accounts deleted in the admin: their photos are personal data.
    instance.avatar.delete(save=False)
    instance.cover.delete(save=False)


class ReactionKind(models.TextChoices):
    LIKE = "like", "Like"
    LOVE = "love", "Love"
    CELEBRATE = "celebrate", "Celebrate"
    LAUGH = "laugh", "Haha"
    WOW = "wow", "Wow"
    SAD = "sad", "Sad"


class Reaction(models.Model):
    Kind = ReactionKind
    EMOJI = {"like": "👍", "love": "❤️", "celebrate": "🎉", "laugh": "😂", "wow": "😮", "sad": "😢"}

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reactions")
    kind = models.CharField(max_length=20, choices=ReactionKind.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="one_reaction_per_person")]


class CommentReaction(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comment_reactions")
    kind = models.CharField(max_length=20, choices=ReactionKind.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["comment", "user"], name="one_comment_reaction_per_person")]


class Event(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=5000, blank=True)
    location = models.CharField(max_length=200, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, null=True, blank=True, related_name="events", verbose_name="group"
    )
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="events_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("event", args=[self.pk])

    def can_view(self, user):
        return self.community is None or self.community.can_view(user)


class RSVP(models.Model):
    class Status(models.TextChoices):
        GOING = "going", "Going"
        MAYBE = "maybe", "Maybe"
        DECLINED = "declined", "Can't go"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="rsvps")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rsvps")
    status = models.CharField(max_length=10, choices=Status.choices)
    # Minutes before the start to be reminded, for this event only. Empty: use the person's own default.
    reminders = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="one_rsvp_per_person")]
        verbose_name = "RSVP"

    def reminder_minutes(self):
        return self.user.event_reminders if self.reminders is None else self.reminders


class ReminderSent(models.Model):
    """Remembers which event reminders went out, so nobody is reminded twice."""

    rsvp = models.ForeignKey(RSVP, on_delete=models.CASCADE, related_name="sent_reminders")
    minutes = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["rsvp", "minutes"], name="one_reminder_per_time")]


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    category = models.CharField(max_length=20, default="general")
    message = models.CharField(max_length=300)
    url = models.CharField(max_length=300)
    invite = models.ForeignKey(GroupInvite, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    pushed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"]), models.Index(fields=["pushed_at", "created_at"])]

    def __str__(self):
        return self.message


def notify(recipients, actor, message, url, category="general", invite=None):
    """Create an in-app notification for each recipient, skipping the person who did the action.

    Push and email follow later (see the tick and send_digests commands), by each person's settings.
    """
    people = [r for r in recipients if actor is None or r.pk != actor.pk]
    if category in OPT_IN_TYPES:
        people = [r for r in people if r.wants(category, "push") or r.wants(category, "email")]
    Notification.objects.bulk_create(
        Notification(recipient=r, actor=actor, category=category, message=message[:300], url=url, invite=invite)
        for r in people
    )


class PushSubscription(models.Model):
    """A browser or home-screen app that agreed to receive push notifications for this person."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    device = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class FeatureNote(models.Model):
    """An entry on the "What's new" page."""

    title = models.CharField(max_length=120)
    body = models.TextField(max_length=2000)
    published_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-published_at"]
        verbose_name = "what's new entry"
        verbose_name_plural = "what's new entries"

    def __str__(self):
        return self.title


class Report(models.Model):
    """A colleague flagging a post, a comment or a person for a moderator."""

    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    person = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="reports_about")
    reason = models.TextField(max_length=3000)
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(post__isnull=False, comment__isnull=True, person__isnull=True)
                    | Q(post__isnull=True, comment__isnull=False, person__isnull=True)
                    | Q(post__isnull=True, comment__isnull=True, person__isnull=False)
                ),
                name="report_exactly_one_target",
            )
        ]

    def __str__(self):
        return f"Report on {self.target_label}"

    @property
    def target(self):
        return self.post or self.comment or self.person

    @property
    def target_label(self):
        if self.post_id:
            return f"post {self.post_id}"
        if self.comment_id:
            return f"comment {self.comment_id}"
        return f"person {self.person_id}"
