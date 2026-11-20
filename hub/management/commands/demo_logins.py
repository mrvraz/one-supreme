"""Gives one person two sign-ins for the demo: <first>.admin sees everything, <first>.staff is a normal colleague.

Run after seed_demo. Each run sets a new password and prints it once. Demo servers only.
"""

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from chat.models import Conversation, Membership
from hub.models import Community, User, notify

STAFF_PLACES = ["head-office", "marketing", "manchester-office", "running-club", "photography"]


class Command(BaseCommand):
    help = "Create or reset two demo sign-ins for one person, e.g. demo_logins Amy Chambers --force."

    def add_arguments(self, parser):
        parser.add_argument("first_name")
        parser.add_argument("last_name")
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off (demo servers).")

    def handle(self, *args, first_name, last_name, force, **options):
        if not (settings.DEBUG or force):
            raise CommandError("demo_logins is for demos only. Use --force on a demo server, never on a live system.")
        head_office = Community.objects.filter(slug="head-office").first()
        if not head_office:
            raise CommandError("Run seed_demo first: the demo logins join its teams and groups.")

        password = secrets.token_urlsafe(12)
        name = first_name.lower()
        admin, new_admin = self.account(f"{name}.admin", first_name, last_name, "Hub administrator", "People", password, True)
        staff, new_staff = self.account(f"{name}.staff", first_name, last_name, "Marketing Coordinator", "Marketing", password, False)

        # The admin is in every team and group, the private one too, and manages the organisation units.
        admin.communities.add(*Community.objects.all())
        admin.communities_managed.add(*Community.objects.filter(kind=Community.UNIT))
        # The staff login sits where a marketing colleague at the Manchester office would.
        staff.communities.add(*Community.objects.filter(slug__in=STAFF_PLACES))
        crew = Conversation.objects.filter(is_group=True, name="Summer social crew").first()
        if crew:
            for person in (admin, staff):
                Membership.objects.get_or_create(conversation=crew, user=person)
        newcomers = [person for person, new in [(admin, new_admin), (staff, new_staff)] if new]
        if newcomers:
            notify(newcomers, head_office.created_by, f"Welcome to the demo, {first_name}! Have a look around.", "/")

        self.stdout.write(
            f"Sign in at {settings.SITE_URL}/login/\n"
            f"  {admin.username}  (admin: sees and manages everything)\n"
            f"  {staff.username}  (a normal colleague)\n"
            f"Password for both: {password}"
        )

    @staticmethod
    def account(username, first, last, title, department, password, admin):
        person, created = User.objects.update_or_create(username=username, defaults={
            "first_name": first, "last_name": last, "email": f"{username}@example.com", "job_title": title,
            "department": department, "start_date": timezone.localdate(), "is_active": True,
            "is_staff": admin, "is_superuser": admin,
        })
        person.set_password(password)
        person.save(update_fields=["password"])
        return person, created
