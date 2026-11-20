from django.conf import settings
from django.db import models
from django.db.models import OuterRef
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone


class Conversation(models.Model):
    """A one-to-one chat between two colleagues, or a named group chat."""

    is_group = models.BooleanField(default=False)
    name = models.CharField(max_length=80, blank=True)  # group chats only
    # "lower user id:higher user id" for one-to-one chats, so the database allows only one per pair.
    pair = models.CharField(max_length=41, unique=True, null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    def __str__(self):
        return self.name or f"Chat {self.pk}"

    def get_absolute_url(self):
        return reverse("chat:thread", args=[self.pk])

    def other(self, user):
        """The other person in a one-to-one chat. None in a group chat, or once their account has been removed."""
        if self.is_group:
            return None
        return next((m.user for m in self.memberships.all() if m.user_id != user.pk), None)

    def label_for(self, user):
        return self.name if self.is_group else str(self.other(user) or "Former colleague")

    def manager_id(self):
        """Who adds and removes people in a group chat: whoever started it (or took it over) while they are still an
        active member. Once they have left the chat or the company, the longest-standing active member."""
        active = self.memberships.filter(user__is_active=True)
        if self.created_by_id and active.filter(user_id=self.created_by_id).exists():
            return self.created_by_id
        heir = active.order_by("joined_at", "pk").first()
        return heir.user_id if heir else None


class Membership(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
    joined_at = models.DateTimeField(default=timezone.now)
    last_read_at = models.DateTimeField(default=timezone.now)
    muted = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="one_membership_per_person")]

    def __str__(self):
        return f"{self.user} in {self.conversation}"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    body = models.TextField(max_length=4000, blank=True)
    image = models.ImageField(upload_to="chat/%Y/%m/", blank=True, db_index=True)  # looked up on every picture request
    created_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]
        indexes = [models.Index(fields=["conversation", "created_at"]), models.Index(fields=["sender", "created_at"])]

    def __str__(self):
        return self.body[:60] or "(picture)"


@receiver(post_delete, sender=Message)
def _delete_message_image(sender, instance, **kwargs):
    # Removed messages must not leave their pictures behind on disk.
    if instance.image:
        instance.image.delete(save=False)


def unread():
    """For Membership querysets: the messages that member has not read yet. Use with Exists() or count it in a Subquery."""
    return Message.objects.filter(
        conversation=OuterRef("conversation"), created_at__gt=OuterRef("last_read_at"), deleted_at__isnull=True
    ).exclude(sender=OuterRef("user"))
