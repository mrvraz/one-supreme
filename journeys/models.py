"""Journeys: short step-by-step paths (onboarding, a safety refresher) given to people to work through."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from hub.models import Community, notify


class JourneyQuerySet(models.QuerySet):
    def reaching(self, user):
        """Published journeys meant for this person: for everyone, or for a group or unit they belong to."""
        mine = user.communities.all()
        return self.filter(Q(audiences__isnull=True) | Q(audiences__in=mine), is_published=True).distinct()


class Journey(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=2000, blank=True)
    cover = models.ImageField(upload_to="journeys/", blank=True)
    # Empty means everyone.
    audiences = models.ManyToManyField(Community, blank=True, related_name="journeys")
    is_published = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    objects = JourneyQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("journeys:detail", args=[self.pk])

    def audience(self):
        """The active people this journey is meant for."""
        people = get_user_model().objects.filter(is_active=True)
        if self.audiences.exists():
            people = people.filter(communities__in=self.audiences.all()).distinct()
        return people


class Step(models.Model):
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name="steps")
    position = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=200)
    body = models.TextField(max_length=20000, blank=True)
    # http and https only, so a link can never run a script.
    link_url = models.URLField(max_length=500, blank=True, validators=[URLValidator(schemes=["http", "https"])])

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return self.title


class Assignment(models.Model):
    """A journey given to one person, and when they finished it."""

    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="journey_assignments")
    assigned_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["journey", "user"], name="one_assignment_per_person")]

    def __str__(self):
        return f"{self.journey} / {self.user}"


class StepDone(models.Model):
    step = models.ForeignKey(Step, on_delete=models.CASCADE, related_name="done")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="journey_steps_done")
    done_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["step", "user"], name="one_tick_per_step_and_person")]


@receiver(post_delete, sender=Journey)
def _delete_cover_file(sender, instance, **kwargs):
    if instance.cover:
        instance.cover.delete(save=False)


def assign(journey, users):
    """Give the journey to those of `users` who don't have it yet, and tell each of them once."""
    have = set(journey.assignments.filter(user__in=users).values_list("user_id", flat=True))
    new = [user for user in users if user.pk not in have]
    # shortcut: two requests at the very same moment could both send the notification (the row itself stays
    # unique); switch to get_or_create per person if anyone reports a double alert.
    Assignment.objects.bulk_create([Assignment(journey=journey, user=user) for user in new], ignore_conflicts=True)
    message = f"New journey for you: {journey.title}"
    notify(new, journey.created_by, message, journey.get_absolute_url(), category="journeys")


def ensure_assignments(user):
    """Give this person every published journey that reaches them and that they don't have yet."""
    missing = Journey.objects.reaching(user).exclude(assignments__user=user).select_related("created_by")
    for journey in missing:
        assign(journey, [user])


@receiver(m2m_changed, sender=Community.members.through)
def _assign_to_new_members(sender, instance, action, reverse, pk_set, **kwargs):
    """Someone joined a team or group after its journeys were published: they get them now, not when they
    happen to open Journeys. Works from either side: group.members.add(person) or person.communities.add(group)."""
    if action != "post_add" or not pk_set:
        return
    people = [instance] if reverse else get_user_model().objects.filter(pk__in=pk_set)
    for person in people:
        if person.is_active:
            ensure_assignments(person)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def _assign_to_new_joiners(sender, instance, created, **kwargs):
    """A new account (e.g. a starter's first sign-in) gets the journeys meant for everyone straight away."""
    if created and instance.is_active:
        ensure_assignments(instance)
