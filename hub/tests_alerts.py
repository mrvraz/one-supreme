"""Security alerts (hub/alerts.py) and the events that feed them. docs/operations/SECURITY-ALERTS.md lists them."""

import io
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import checks, mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from library.models import Document

from .alerts import RULES
from .auth import EmployeeOIDCBackend
from .security import audit
from .tests import make_user

TEMP_MEDIA = tempfile.mkdtemp()


@override_settings(ADMINS=[("IT", "it@example.com")], MEDIA_ROOT=TEMP_MEDIA)
class SecurityAlertTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()  # the counts live in the cache, which outlasts a test
        clock = mock.patch("hub.alerts.time")
        self.clock = clock.start().time
        self.clock.return_value = 1_800_000_000  # the start of a window, so no test straddles two
        self.addCleanup(clock.stop)
        self.alice = make_user("alice")
        self.bob = make_user("bob")

    def events(self, logs, name):
        return [r.details for r in logs.records if r.getMessage() == name]

    def repeat(self, times, event, **details):
        with self.assertLogs("hub.security", "INFO"):  # also keeps the JSON lines out of the test output
            for _ in range(times):
                audit(event, level=logging.WARNING, **details)

    def test_admin_rights_given_or_taken_are_logged_and_emailed_each_time(self):
        moderators = Group.objects.create(name="Moderators")
        change_post = Permission.objects.get(codename="change_post")
        with self.assertLogs("hub.security", "WARNING") as logs, self.captureOnCommitCallbacks(execute=True):
            self.bob.is_staff = True
            self.bob.save()
            self.bob.groups.add(moderators)
            moderators.permissions.add(change_post)
            self.bob.user_permissions.add(change_post)
            moderators.user_set.remove(self.bob)
            self.bob.is_staff = False
            self.bob.save()
            make_user("root", is_superuser=True)
        changes = [(e["target"], e["change"]) for e in self.events(logs, "admin_rights_changed")]
        self.assertEqual(changes, [
            ("bob@example.com", "given staff status (opens the admin)"),
            ("bob@example.com", "group added: Moderators"),
            ("Moderators", "permission added: Staff hub | post | Can change post"),
            ("bob@example.com", "permission added: Staff hub | post | Can change post"),
            ("Moderators", "user removed: bob@example.com"),
            ("bob@example.com", "lost staff status (opens the admin)"),
            ("root@example.com", "given superuser (every permission)"),
        ])
        self.assertEqual(len(mail.outbox), 7)
        self.assertEqual(mail.outbox[0].subject, "Staff hub: admin rights changed")
        self.assertEqual(mail.outbox[0].to, ["it@example.com"])
        self.assertIn('target: "bob@example.com"', mail.outbox[0].body)
        self.assertIn('see "Admin rights changed" in docs/operations/SECURITY-ALERTS.md', mail.outbox[0].body)

    def test_waking_a_dormant_admin_or_giving_it_a_password_is_an_alert(self):
        root = make_user("root", is_superuser=True, is_active=False)
        carol = make_user("carol", is_active=False)
        carol.groups.add(Group.objects.create(name="Moderators"))
        with self.assertLogs("hub.security", "WARNING") as logs, self.captureOnCommitCallbacks(execute=True):
            root.is_active = True
            root.save()
            root.set_password("pw2")
            root.save()
            carol.is_active = True
            carol.save(update_fields=["is_active"])
            self.bob.is_active = False  # an ordinary account: switching it off and on, or a new password, is no alert
            self.bob.save()
            self.bob.is_active = True
            self.bob.set_password("pw2")
            self.bob.save()
        changes = [(e["target"], e["change"]) for e in self.events(logs, "admin_rights_changed")]
        self.assertEqual(changes, [
            ("root@example.com", "admin account switched back on"),
            ("root@example.com", "admin account given a new password"),
            ("carol@example.com", "admin account switched back on"),
        ])
        self.assertEqual(len(mail.outbox), 3)

    def test_deleting_an_admin_account_or_a_role_with_members_is_an_alert(self):
        moderators = Group.objects.create(name="Moderators")
        self.bob.groups.add(moderators)
        empty = Group.objects.create(name="Editors")
        root = make_user("root", is_superuser=True)
        with self.assertLogs("hub.security", "WARNING") as logs, self.captureOnCommitCallbacks(execute=True):
            self.bob.groups.add(moderators)  # already in it: nothing changed, no email
            get_user_model().objects.filter(pk=root.pk).delete()  # as the admin's "Delete selected" does
            moderators.delete()
            empty.delete()  # nobody loses anything
            self.alice.delete()  # an ordinary account
        changes = [(e["target"], e["change"]) for e in self.events(logs, "admin_rights_changed")]
        self.assertEqual(changes, [
            ("root@example.com", "admin account deleted"),
            ("Moderators", "role deleted (members: bob@example.com)"),
        ])
        self.assertEqual(len(mail.outbox), 2)

    def test_the_playbooks_sign_out_step_ends_a_stolen_session(self):
        self.client.force_login(self.bob)  # the attacker's copy of the session
        self.assertEqual(self.client.get("/").status_code, 200)
        self.bob.is_active = False  # INCIDENT-PLAYBOOKS.md, playbook 1, step 2
        self.bob.save()
        self.bob.set_unusable_password()
        self.bob.save()
        self.bob.is_active = True  # step 9, once the account is clean
        self.bob.save()
        self.assertRedirects(self.client.get("/"), "/login/?next=/", fetch_redirect_response=False)

    def test_ordinary_saves_and_undone_changes_send_nothing(self):
        with self.assertNoLogs("hub.security", "WARNING"), self.captureOnCommitCallbacks(execute=True) as done:
            self.bob.job_title = "Picker"
            self.bob.save()
            self.bob.save(update_fields=["last_login"])
            try:
                with transaction.atomic():  # an admin form that failed after the save
                    self.alice.is_superuser = True
                    self.alice.save()
                    raise ValueError
            except ValueError:
                pass
        self.assertEqual(done, [])
        self.assertEqual(mail.outbox, [])

    def test_many_failed_sign_ins_send_one_email_per_window(self):
        self.repeat(9, "sign_in_failed", username="breakglass")
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "sign_in_rejected", email="guest@partner.com\nevent: nothing to see")  # refused SSO counts too
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: many failed sign-ins"])
        self.assertIn("10 times within 15 minutes.", mail.outbox[0].body)
        # Typed text stays inside its own line, so it can't pass for a line of the email.
        self.assertIn('email: "guest@partner.com\\nevent: nothing to see"', mail.outbox[0].body)
        self.assertNotIn("\nevent: nothing to see", mail.outbox[0].body)
        self.repeat(20, "sign_in_failed", username="breakglass")
        self.assertEqual(len(mail.outbox), 1)  # the rest of the attack doesn't flood the mailbox
        self.clock.return_value += 16 * 60
        self.repeat(10, "sign_in_failed", username="breakglass")
        self.assertEqual(len(mail.outbox), 2)  # a new window, a new email

    @override_settings(
        AUTHENTICATION_BACKENDS=["hub.auth.EmployeeOIDCBackend"], ALLOWED_EMAIL_DOMAINS=["example.com"],
        OIDC_OP_TOKEN_ENDPOINT="https://sso.invalid/token", OIDC_OP_USER_ENDPOINT="https://sso.invalid/userinfo",
        OIDC_RP_CLIENT_ID="hub", OIDC_RP_CLIENT_SECRET="", OIDC_RP_SIGN_ALGO="HS256",
    )
    def test_each_refused_single_sign_on_counts_once(self):
        request = RequestFactory().get("/oidc/callback/", {"code": "c", "state": "s"})
        request.session = {}

        def sign_in(email):  # Microsoft's side is faked; the hub's backend and Django's authenticate() are real
            with mock.patch.object(OIDCAuthenticationBackend, "get_userinfo", return_value={"email": email}):
                return authenticate(request, nonce=None, code_verifier=None)

        token = {"id_token": "i", "access_token": "a"}
        with (
            mock.patch.object(EmployeeOIDCBackend, "get_token", return_value=token),
            mock.patch.object(EmployeeOIDCBackend, "verify_token", return_value={"oid": "oid-1"}),
            self.assertLogs("hub.security", "WARNING") as logs,
            self.assertLogs("mozilla_django_oidc", "WARNING"),  # its own "Claims verification failed" lines
        ):
            for _ in range(9):
                self.assertIsNone(sign_in("guest@partner.com"))
            self.assertEqual(mail.outbox, [])
            self.bob.is_active = False
            self.bob.save()
            self.assertEqual(sign_in("bob@example.com"), self.bob)  # the callback view then turns him away
        self.assertEqual([r.getMessage() for r in logs.records], ["sign_in_rejected"] * 10 + ["security_alert"])
        self.assertEqual(logs.records[9].details["reason"], "account switched off")
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: many failed sign-ins"])

    def test_one_person_hitting_the_limits_again_and_again(self):
        self.repeat(4, "rate_limited", user=self.alice, limit="post")
        self.repeat(4, "rate_limited", user=self.bob, limit="post")
        self.repeat(9, "rate_limited", limit="sign_in")  # nobody signed in: not anyone's count
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "rate_limited", user=self.alice, limit="comment")
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: one person keeps hitting the limits"])
        self.assertIn('5 times within an hour, all by "alice@example.com".', mail.outbox[0].body)

    def test_downloads_are_logged_once_per_file_by_name_and_id_and_a_hundred_in_a_day_is_an_alert(self):
        doc = Document.objects.create(  # stored under a random name, as library/files.py does
            title="Pay bands", file=SimpleUploadedFile(uuid.uuid4().hex + ".pdf", b"%PDF-1.7\n%%EOF"),
            original_name="Pay bands 2026.pdf", size=14, uploaded_by=self.bob,
        )
        os.makedirs(os.path.join(TEMP_MEDIA, "avatars"), exist_ok=True)
        with open(os.path.join(TEMP_MEDIA, "avatars", "bob.png"), "wb") as fh:
            fh.write(b"\x89PNG")
        # Through the real "security" handler, with whatever filters settings.LOGGING gives it (log redaction too).
        handler = next(h for h in logging.getLogger("hub.security").handlers if h.name == "security")
        self.addCleanup(handler.setStream, handler.setStream(io.StringIO()))
        self.client.force_login(self.alice)
        thief = Client(REMOTE_ADDR="203.0.113.9")  # alice again, from another session and network address
        thief.force_login(self.alice)
        self.assertEqual(self.client.get(doc.file.url).status_code, 200)
        self.assertEqual(self.client.get(doc.file.url, HTTP_RANGE="bytes=1000-").status_code, 200)  # the same file
        self.assertEqual(self.client.get("/media/avatars/bob.png").status_code, 200)  # shown, not downloaded
        self.assertEqual(thief.get(doc.file.url, HTTP_RANGE="bytes=1-").status_code, 200)
        lines = [json.loads(line) for line in handler.stream.getvalue().splitlines()]
        downloads = [(e["name"], e["document_id"], e["user"], e["ip"]) for e in lines if e["event"] == "file_downloaded"]
        self.assertEqual(downloads, [
            ("Pay bands 2026.pdf", doc.pk, "alice@example.com", "127.0.0.1"),
            ("Pay bands 2026.pdf", doc.pk, "alice@example.com", "203.0.113.9"),
        ])
        self.repeat(97, "file_downloaded", user=self.alice, name=doc.original_name)
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "file_downloaded", user=self.alice, name=doc.original_name)
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: one person is downloading many files"])

    def test_repeated_data_exports(self):
        self.repeat(2, "data_exported", user=self.alice)
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "data_exported", user=self.alice)
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: one person keeps exporting their data"])

    def test_two_events_at_the_same_moment_send_one_email(self):
        with mock.patch.object(cache, "get", return_value=2):  # both read the count before either wrote it
            self.repeat(2, "data_exported", user=self.alice)
        self.assertEqual(len(mail.outbox), 1)

    def test_the_deploy_check_says_when_alerts_reach_nobody(self):
        def found():
            return [m.id for m in checks.run_checks(tags=[checks.Tags.security], include_deployment_checks=True)]

        self.assertNotIn("hub.I001", found())
        with override_settings(ADMINS=[]):
            self.assertIn("hub.I001", found())

    def test_every_alert_is_in_the_alerts_document_and_nothing_else_is(self):
        doc = (settings.BASE_DIR / "docs/operations/SECURITY-ALERTS.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^### (.+)$", doc, re.M))
        self.assertEqual(documented, {alert for alert, *_ in RULES.values()})
