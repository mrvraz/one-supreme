from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from hub.models import matching


class VacancyQuerySet(models.QuerySet):
    def open(self):
        """Not closed by an editor, and the closing date (if there is one) is today or later."""
        return self.filter(Q(closes_on__isnull=True) | Q(closes_on__gte=timezone.localdate()), is_open=True)

    def closed(self):
        return self.filter(Q(is_open=False) | Q(closes_on__lt=timezone.localdate()))

    def search(self, q):
        return matching(self, q, "title", "location", "department")


class Vacancy(models.Model):
    CONTRACT_TYPES = [("full", "Full-time"), ("part", "Part-time"), ("temp", "Temporary"), ("apprentice", "Apprenticeship")]

    title = models.CharField("Job title", max_length=200)
    location = models.CharField(max_length=120)
    department = models.CharField(max_length=120)
    contract_type = models.CharField(max_length=20, choices=CONTRACT_TYPES, default="full")
    salary = models.CharField(max_length=120, blank=True, help_text="Optional. For example: £26,000 a year.")
    description = models.TextField(
        max_length=10000, help_text="You can use **bold**, *italic*, lists (start a line with - or 1.) and links."
    )
    closes_on = models.DateField(
        "Closing date", null=True, blank=True, help_text="Optional. The last day people can say they're interested."
    )
    # Not a URLField: that also accepts ftp://, and its form field guesses "http://" when the start is missing.
    apply_url = models.CharField(
        "Public careers page",
        max_length=500,
        blank=True,
        validators=[URLValidator(schemes=["http", "https"])],
        help_text="Optional. The advert on the public website, so staff can share it with friends.",
    )
    contact = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"is_active": True},
        verbose_name="Recruiter",
        help_text="Optional. This person is told when someone is interested. If empty, whoever added the vacancy is told.",
    )
    is_open = models.BooleanField(default=True, help_text="Off once an editor closes the vacancy")
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = VacancyQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name_plural = "vacancies"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # People's interest is removed 180 days after a vacancy closes (see hooks.purge), so note when that was.
        self.closed_at = None if self.is_open else (self.closed_at or timezone.now())
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("jobs:detail", args=[self.pk])

    @property
    def open_now(self):
        """The same rule as VacancyQuerySet.open(), for one vacancy."""
        return self.is_open and (self.closes_on is None or self.closes_on >= timezone.localdate())


class Interest(models.Model):
    """Someone said they'd like to hear more about a vacancy. Only they, the recruiter and vacancy editors can see it."""

    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name="interests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_interests")
    note = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["vacancy", "user"], name="one_job_interest_per_person")]

    def __str__(self):
        return f"{self.user} / {self.vacancy}"
