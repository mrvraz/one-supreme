"""Security alerts (hub/alerts.py) and the events that feed them. docs/operations/SECURITY-ALERTS.md lists them."""

import logging
import os
import re
import shutil
import tempfile
import time
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings

from library.models import Document

from .alerts import RULES
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
        self.assertIn("target: bob@example.com", mail.outbox[0].body)
        self.assertIn('see "Admin rights changed" in docs/operations/SECURITY-ALERTS.md', mail.outbox[0].body)

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
        self.repeat(1, "sign_in_rejected", email="guest@partner.com")  # refused single sign-ons count too
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: many failed sign-ins"])
        self.assertIn("10 times within 15 minutes.", mail.outbox[0].body)
        self.assertIn("email: guest@partner.com", mail.outbox[0].body)
        self.repeat(20, "sign_in_failed", username="breakglass")
        self.assertEqual(len(mail.outbox), 1)  # the rest of the attack doesn't flood the mailbox
        with mock.patch("hub.alerts.time.time", return_value=time.time() + 16 * 60):
            self.repeat(10, "sign_in_failed", username="breakglass")
        self.assertEqual(len(mail.outbox), 2)  # a new window, a new email

    def test_one_person_hitting_the_limits_again_and_again(self):
        self.repeat(4, "rate_limited", user=self.alice, limit="post")
        self.repeat(4, "rate_limited", user=self.bob, limit="post")
        self.repeat(9, "rate_limited", limit="sign_in")  # nobody signed in: not anyone's count
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "rate_limited", user=self.alice, limit="comment")
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: one person keeps hitting the limits"])
        self.assertIn("5 times within an hour, all by alice@example.com.", mail.outbox[0].body)

    def test_downloads_are_logged_and_a_hundred_in_a_day_is_an_alert(self):
        doc = Document.objects.create(
            title="Pay bands", file=SimpleUploadedFile("pay.pdf", b"%PDF-1.7\n%%EOF"), original_name="pay.pdf",
            size=14, uploaded_by=self.bob,
        )
        os.makedirs(os.path.join(TEMP_MEDIA, "avatars"), exist_ok=True)
        with open(os.path.join(TEMP_MEDIA, "avatars", "bob.png"), "wb") as fh:
            fh.write(b"\x89PNG")
        self.client.force_login(self.alice)
        with self.assertLogs("hub.security", "INFO") as logs:
            self.assertEqual(self.client.get(doc.file.url).status_code, 200)
            self.assertEqual(self.client.get("/media/avatars/bob.png").status_code, 200)  # shown, not downloaded
        downloads = self.events(logs, "file_downloaded")
        self.assertEqual([(d["file"], d["user"]) for d in downloads], [(doc.file.name, "alice@example.com")])
        self.repeat(98, "file_downloaded", user=self.alice, file=doc.file.name)
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "file_downloaded", user=self.alice, file=doc.file.name)
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: one person is downloading many files"])

    def test_repeated_data_exports(self):
        self.repeat(2, "data_exported", user=self.alice)
        self.assertEqual(mail.outbox, [])
        self.repeat(1, "data_exported", user=self.alice)
        self.assertEqual([m.subject for m in mail.outbox], ["Staff hub: one person keeps exporting their data"])

    def test_every_alert_is_in_the_alerts_document_and_nothing_else_is(self):
        doc = (settings.BASE_DIR / "docs/operations/SECURITY-ALERTS.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^### (.+)$", doc, re.M))
        self.assertEqual(documented, {alert for alert, *_ in RULES.values()})
