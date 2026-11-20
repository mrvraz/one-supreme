"""What the jobs board plugs into hub's shared pages. Registered in apps.py (see hub/plugins.py)."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Interest, Vacancy

KEEP_INTEREST_DAYS = 180


def search(user, q, limit):
    found = Vacancy.objects.open().search(q)[:limit]
    return "Jobs", [(v.title, v.get_absolute_url(), f"{v.location} · {v.department}") for v in found]


def export(user):
    """The vacancies this person said they were interested in, for "Download my data"."""
    return "jobs", list(Interest.objects.filter(user=user).values("vacancy__title", "note", "created_at")), []


def purge(now):
    """Forget who was interested once a vacancy has been closed for KEEP_INTEREST_DAYS, by an editor or by its date."""
    closed_by_editor = Q(vacancy__is_open=False, vacancy__closed_at__lt=now - timedelta(days=KEEP_INTEREST_DAYS))
    closed_by_date = Q(vacancy__closes_on__lt=timezone.localdate(now) - timedelta(days=KEEP_INTEREST_DAYS))
    return "old job interests", Interest.objects.filter(closed_by_editor | closed_by_date).delete()[0]
