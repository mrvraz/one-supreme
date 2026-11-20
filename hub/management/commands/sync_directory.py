"""Switches off hub accounts for people who've left, using Microsoft Entra ID as the source of truth.

Needs the Entra app registration to have the Microsoft Graph *application* permission User.Read.All,
with admin consent. Signing in is already blocked for leavers; this also ends every session they still have
(a switched-off account is refused on every request) and takes them out of the directory. The scheduler runs it
every 15 minutes, quietly, and once a day at 05:00 UTC with an email to the admins if it fails.
"""

import logging

import requests
from django.conf import settings
from django.core.mail import mail_admins
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from hub.models import User
from hub.security import audit

GRAPH_USERS = "https://graph.microsoft.com/v1.0/users?$select=id,mail,userPrincipalName,accountEnabled&$top=999"


class Command(BaseCommand):
    help = "Switch off accounts of people removed or disabled in Microsoft Entra ID. Run every 15 minutes."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show who would be switched off, change nothing.")
        parser.add_argument("--force", action="store_true", help="Allow switching off more than a fifth of accounts.")
        parser.add_argument("--no-email", action="store_true", help="Don't email the admins when it fails, only log it.")

    def handle(self, *args, **options):
        self.email_on_failure = not options["no_email"]
        token_url = getattr(settings, "OIDC_OP_TOKEN_ENDPOINT", "")
        if not token_url.startswith("https://login.microsoftonline.com/"):
            self.stdout.write("Skipped: single sign-on isn't Microsoft Entra ID.")
            return
        try:
            ids, addresses = self.enabled_people(token_url)
        except (requests.RequestException, KeyError) as exc:
            self.fail(f"Couldn't read the staff directory from Microsoft: {exc}")

        # Only single sign-on accounts. Password accounts (the break-glass admin) are left alone, but an account
        # linked to single sign-on is checked even if someone gave it a password.
        sso_accounts = list(User.objects.filter(Q(password__startswith="!") | Q(sso_id__isnull=False), is_active=True))
        # Linked accounts are checked by their permanent ID, so a renamed person isn't mistaken for a leaver.
        leavers = [u for u in sso_accounts if (u.sso_id not in ids if u.sso_id else u.email.lower() not in addresses)]

        if options["dry_run"]:
            for person in leavers:
                self.stdout.write(f"Would switch off: {person.email}")
        elif len(leavers) > max(5, len(sso_accounts) // 5) and not options["force"]:
            # A wrong permission or an empty answer from Microsoft must not lock out the whole company.
            self.fail(
                f"Would switch off {len(leavers)} of {len(sso_accounts)} accounts, which looks wrong. "
                "Nothing was changed. Check with --dry-run, then rerun with --force if it's right."
            )
        else:
            for person in leavers:
                self.stdout.write(f"Switching off: {person.email}")
                person.is_active = False
                person.save(update_fields=["is_active"])
                audit("account_deactivated", user_id=person.pk, email=person.email, reason="not in directory")
        self.stdout.write(f"Checked {len(sso_accounts)} accounts; {len(leavers)} no longer in the directory.")

    def fail(self, message):
        """Tell the admins by email (ADMIN_EMAILS): a silent failure would leave leavers listed for weeks."""
        audit("directory_sync_failed", level=logging.ERROR, error=message)
        if self.email_on_failure:
            mail_admins("Staff hub: leaver check failed", message)
        raise CommandError(message)

    def enabled_people(self, token_url):
        """IDs and lower-cased email addresses of every enabled account in the directory."""
        token = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.OIDC_RP_CLIENT_ID,
                "client_secret": settings.OIDC_RP_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        token.raise_for_status()
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
        ids, addresses, url = set(), set(), GRAPH_USERS
        while url:  # Graph returns up to 999 people per page
            page = requests.get(url, headers=headers, timeout=30)
            page.raise_for_status()
            body = page.json()
            for person in body["value"]:
                if person.get("accountEnabled"):
                    ids.add(person.get("id"))
                    addresses.update(a.lower() for a in (person.get("mail"), person.get("userPrincipalName")) if a)
            url = body.get("@odata.nextLink")
        return ids, addresses
