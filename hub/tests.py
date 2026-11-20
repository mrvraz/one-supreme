import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import timedelta
from io import BytesIO, StringIO
from unittest import mock, skipUnless

import requests as real_requests
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core import mail
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageCms

from .auth import EmployeeOIDCBackend
from .models import RSVP, Attachment, Comment, Community, Event, Notification, Post, Reaction, Report, User
from .security import JsonFormatter

TEMP_MEDIA = tempfile.mkdtemp()
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def jpeg_with_exif(size=(3000, 2000)):
    """A photo carrying camera data and a 'rotate 90°' orientation flag, like one straight off a phone."""
    img = Image.new("RGB", size, "red")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[0x0112] = 6  # orientation: rotate 90° clockwise
    buf = BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return SimpleUploadedFile("holiday.jpg", buf.getvalue(), content_type="image/jpeg")


def video_with_location():
    """A one-second MP4 tagged with a GPS position, like a phone video."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
             "-c:v", "libx264", "-metadata", "location=+51.5072-000.1276/", path],
            check=True,
        )
        with open(path, "rb") as fh:
            return SimpleUploadedFile("clip.mp4", fh.read(), content_type="video/mp4")


def make_user(name, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)
    return User.objects.create_user(name, f"{name}@example.com", "pw", first_name=name.title(), **extra)


@override_settings(MEDIA_ROOT=TEMP_MEDIA, ALLOW_PASSWORD_LOGIN=True)
class HubTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.mod = make_user("mod", is_staff=True, is_superuser=True)
        self.client.force_login(self.alice)

    def post_as(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse("feed"), data)

    def photo_post(self):
        self.client.post(reverse("feed"), {"body": "", "files": [jpeg_with_exif((100, 100))]})
        return Attachment.objects.latest("pk")

    # --- access ---------------------------------------------------------------
    def test_everything_needs_sign_in(self):
        self.client.logout()
        for url in [reverse("feed"), reverse("people"), reverse("media", args=["posts/x.jpg"])]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith(reverse("login")))
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.assertEqual(self.client.get(reverse("manifest")).status_code, 200)

    @override_settings(BRAND="supreme")
    def test_company_logo(self):
        self.assertContains(self.client.get(reverse("feed")), "hub/brand/supreme/icon")  # top bar and home screen
        self.client.logout()
        login = self.client.get(reverse("login"))
        self.assertContains(login, "hub/brand/supreme/logo")
        self.assertContains(login, "hub/brand/supreme/logo-white")
        self.assertEqual(self.client.get(reverse("manifest")).json()["icons"][0]["type"], "image/png")
        self.assertIn("hub/brand/supreme/icon", self.client.get(reverse("icon"))["Location"])  # push notifications

    def test_sun_moon_button_saves_the_look(self):
        switch = reverse("look_switch")
        self.assertContains(self.client.get(reverse("feed")), 'name="look" value="daylight-dark"')  # "match my device" shows light
        response = self.client.post(switch, {"look": "daylight-dark"}, HTTP_REFERER=reverse("people"))
        self.assertEqual(response["Location"], reverse("people"))  # back to the same page
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.look, "daylight-dark")
        self.assertContains(self.client.get(reverse("feed")), 'data-look="daylight-dark"')
        self.assertEqual(self.client.post(switch, {"look": "daylight"}, HTTP_X_FRAGMENT="1").status_code, 204)  # app.js
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.look, "daylight")
        self.assertEqual(self.client.post(switch, {"look": "purple"}).status_code, 400)
        self.assertEqual(self.client.post(switch, {"look": "daylight"}, HTTP_REFERER="https://evil.example/")["Location"], reverse("feed"))
        self.assertEqual(self.client.get(switch).status_code, 405)

    @override_settings(ALLOW_PASSWORD_LOGIN=False)
    def test_password_sign_in_can_be_switched_off(self):
        self.client.logout()
        response = self.client.post(reverse("login"), {"username": "alice", "password": "pw"})
        self.assertEqual(response.status_code, 403)

    def test_admin_login_goes_to_the_single_sign_in_page(self):
        self.client.logout()
        response = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(response, reverse("login") + "?next=/admin/", fetch_redirect_response=False)

    def sso_backend(self):
        backend = EmployeeOIDCBackend.__new__(EmployeeOIDCBackend)  # skip __init__, which needs live SSO settings
        backend.UserModel = User
        return backend

    @override_settings(ALLOWED_EMAIL_DOMAINS=["supreme.co.uk"])
    def test_sso_only_lets_in_company_addresses_logs_refusals_and_syncs_names(self):
        backend = self.sso_backend()
        self.assertTrue(backend.verify_claims({"email": "Jo@Supreme.co.uk"}))
        with self.assertLogs("hub.security", "WARNING") as logs:
            self.assertFalse(backend.verify_claims({"email": "guest@partner.com"}))
            self.assertFalse(backend.verify_claims({}))
        self.assertEqual([r.getMessage() for r in logs.records], ["sign_in_rejected", "sign_in_rejected"])
        self.assertEqual(logs.records[0].details["email"], "guest@partner.com")
        user = backend.update_user(self.bob, {"given_name": "Robert", "family_name": "Jones"})
        self.assertEqual(user.get_full_name(), "Robert Jones")
        self.bob.is_active = False
        self.bob.save()
        self.assertIsNone(backend.get_user(self.bob.pk))

    def test_sso_keeps_one_account_when_someone_changes_their_email(self):
        backend = self.sso_backend()
        priya = User.objects.create_user("priya", "priya.shah@example.com")
        # First sign-in: found by email, then linked to Microsoft's permanent ID.
        claims = {"sso_id": "oid-123", "email": "priya.shah@example.com", "given_name": "Priya", "family_name": "Shah"}
        backend.update_user(backend.filter_users_by_claims(claims).get(), claims)
        # After her name change, the directory sends a new email address with the same ID.
        claims = {"sso_id": "oid-123", "email": "priya.jones@example.com", "given_name": "Priya", "family_name": "Jones"}
        found = backend.filter_users_by_claims(claims).get()
        backend.update_user(found, claims)
        self.assertEqual(found.pk, priya.pk)
        priya.refresh_from_db()
        self.assertEqual(priya.email, "priya.jones@example.com")
        # Someone else claiming her new address under a different ID doesn't get her account.
        self.assertFalse(backend.filter_users_by_claims({"sso_id": "oid-999", "email": "priya.jones@example.com"}).exists())

    def test_a_recreated_directory_account_is_refused_until_an_admin_unlinks_the_old_one(self):
        backend = self.sso_backend()
        User.objects.filter(pk=self.bob.pk).update(sso_id="oid-old")
        claims = {"sso_id": "oid-new", "email": self.bob.email, "given_name": "Bob"}  # e.g. a re-hire
        self.assertFalse(backend.filter_users_by_claims(claims).exists())
        # Refused with the normal "couldn't sign you in" page (the library turns this into a failed sign-in), not a 500.
        with self.assertLogs("hub.security", "WARNING"), self.assertRaises(SuspiciousOperation):
            backend.create_user(claims)
        self.assertEqual(User.objects.filter(email=self.bob.email).count(), 1)

        self.client.force_login(self.mod)
        with self.assertLogs("hub.security", "INFO"):
            self.client.post(reverse("admin:hub_user_changelist"), {"action": "unlink_sso", "_selected_action": [self.bob.pk]})
        self.assertEqual(backend.filter_users_by_claims(claims).get(), self.bob)  # the next sign-in links the new ID

    def test_security_headers_block_foreign_scripts_and_framing(self):
        response = self.client.get(reverse("feed"))
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("camera=()", response["Permissions-Policy"])

    def test_sign_in_events_are_logged_as_json(self):
        self.client.logout()
        with self.assertLogs("hub.security", "INFO") as logs:
            self.client.post(reverse("login"), {"username": "alice", "password": "wrong"})
            self.client.post(reverse("login"), {"username": "alice", "password": "pw"})
        events = [json.loads(JsonFormatter().format(r)) for r in logs.records]
        self.assertEqual([e["event"] for e in events], ["sign_in_failed", "sign_in"])
        self.assertEqual(events[0]["username"], "alice")
        self.assertEqual(events[1]["user"], "alice@example.com")

    # --- house rules -----------------------------------------------------------------
    def test_newcomers_accept_the_house_rules_first_and_again_when_they_change(self):
        carol = make_user("carol", policy_version="")
        self.client.force_login(carol)
        response = self.client.get(reverse("events"))
        self.assertRedirects(response, reverse("house_rules") + "?next=/events/", fetch_redirect_response=False)
        response = self.client.post(reverse("house_rules"), {"next": "/events/"})
        self.assertRedirects(response, "/events/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("events")).status_code, 200)
        with override_settings(POLICY_VERSION="2"):
            self.assertEqual(self.client.get(reverse("events")).status_code, 302)
        # next= can't send people to another site
        response = self.client.post(reverse("house_rules"), {"next": "https://evil.example/"})
        self.assertRedirects(response, reverse("feed"), fetch_redirect_response=False)

    # --- posts and media -----------------------------------------------------------
    def test_text_post_shows_in_feed(self):
        self.post_as(self.alice, body="Hello team")
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse("feed")), "Hello team")

    def test_photos_lose_camera_data_and_are_turned_upright(self):
        response = self.client.post(reverse("feed"), {"body": "", "files": [jpeg_with_exif()]})
        self.assertEqual(response.status_code, 302)
        stored = Image.open(Attachment.objects.get().file.path)
        self.assertEqual(len(stored.getexif()), 0)
        self.assertLess(stored.width, stored.height)  # rotated upright
        self.assertLessEqual(max(stored.size), 2048)

    def test_files_that_are_not_photos_or_videos_are_rejected(self):
        bad = SimpleUploadedFile("notes.pdf", b"%PDF-1.4 not a photo", content_type="application/pdf")
        response = self.client.post(reverse("feed"), {"body": "x", "files": [bad]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "isn&#x27;t one we can use. Try JPEG, PNG, GIF, MP4 or WebM.")
        self.assertFalse(Post.objects.exists())

    def test_photos_keep_their_colour_profile(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        buf = BytesIO()
        Image.new("RGB", (50, 50), "red").save(buf, "JPEG", icc_profile=profile)
        self.client.post(reverse("feed"), {"body": "", "files": [SimpleUploadedFile("p3.jpg", buf.getvalue())]})
        self.assertEqual(Image.open(Attachment.objects.get().file.path).info.get("icc_profile"), profile)

    def test_posts_over_the_total_upload_size_are_refused_with_a_message(self):
        with mock.patch("hub.forms.MAX_POST_MB", 0.001):  # about 1 KB, so a small photo is "too big"
            response = self.client.post(reverse("feed"), {"body": "Big", "files": [jpeg_with_exif((400, 400))]})
        self.assertContains(response, "must add up to less than")
        self.assertFalse(Post.objects.exists())

    @skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_iphone_videos_lose_their_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "IMG_0001.MOV")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                 "-c:v", "libx264", "-movflags", "use_metadata_tags",
                 "-metadata", "com.apple.quicktime.location.ISO6709=+51.5072-000.1276+011.000/",
                 "-metadata", "com.apple.quicktime.make=Apple", "-f", "mov", path],
                check=True,
            )
            with open(path, "rb") as fh:
                clip = SimpleUploadedFile("IMG_0001.MOV", fh.read(), content_type="video/quicktime")
        self.client.post(reverse("feed"), {"body": "", "files": [clip]})
        att = Attachment.objects.get()
        self.assertTrue(att.file.name.endswith(".mov"))
        with open(att.file.path, "rb") as fh:
            stored = fh.read()
        self.assertNotIn(b"51.5072", stored)
        self.assertNotIn(b"com.apple.quicktime.make", stored)

    @skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_videos_lose_their_location_and_fakes_are_rejected(self):
        self.client.post(reverse("feed"), {"body": "Clip", "files": [video_with_location()]})
        att = Attachment.objects.get()
        self.assertEqual(att.kind, Attachment.VIDEO)
        self.assertTrue(att.file.name.endswith(".mp4"))
        tags = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", att.file.path],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertNotIn("51.5072", tags)
        fake = SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
        response = self.client.post(reverse("feed"), {"body": "Fake", "files": [fake]})
        self.assertContains(response, "couldn&#x27;t read that video")

    def test_media_is_served_only_inside_the_media_folder(self):
        url = self.photo_post().file.url
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get("/media/../config/settings.py").status_code, 404)
        with self.settings(X_ACCEL_MEDIA=True):
            response = self.client.get(url)
            self.assertTrue(response["X-Accel-Redirect"].startswith("/protected-media/posts/"))
            self.assertEqual(response["Content-Type"], "image/jpeg")

    def test_photos_of_hidden_or_deleted_posts_are_blocked_except_for_moderators(self):
        att = self.photo_post()
        url, post = att.file.url, att.post
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 200)
        Post.objects.filter(pk=post.pk).update(is_hidden=True)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.mod)
        self.assertEqual(self.client.get(url).status_code, 200)
        Post.objects.filter(pk=post.pk).update(is_hidden=False, deleted_at=timezone.now())
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        # Nor through a path that only pretends to be a profile photo.
        self.assertEqual(self.client.get(f"/media/avatars/../{att.file.name}").status_code, 404)

    def test_only_members_can_post_into_a_group(self):
        group = Community.objects.create(name="Running", slug="running")
        self.post_as(self.alice, body="Sneaky", community=group.pk)
        self.assertFalse(Post.objects.exists())
        group.members.add(self.alice)
        self.post_as(self.alice, body="Run on Sunday?", community=group.pk)
        self.assertEqual(Post.objects.get().community, group)

    def test_group_posts_only_reach_members_feeds(self):
        group = Community.objects.create(name="Running", slug="running")
        group.members.add(self.alice)
        Post.objects.create(author=self.alice, community=group, body="Members only feed post")
        self.assertContains(self.client.get(reverse("feed")), "Members only feed post")
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(reverse("feed")), "Members only feed post")

    def test_only_staff_can_pin_announcements_and_everyone_is_told(self):
        self.post_as(self.alice, body="Not an announcement", is_announcement="on")
        self.assertFalse(Post.objects.get().is_announcement)
        self.post_as(self.mod, body="Office closed Monday", is_announcement="on")
        announcement = Post.objects.get(body="Office closed Monday")
        self.assertTrue(announcement.is_announcement)
        self.assertEqual(Notification.objects.filter(url=announcement.get_absolute_url()).count(), 2)

    def test_hidden_posts_disappear(self):
        Post.objects.create(author=self.bob, body="Rude post", is_hidden=True)
        self.assertNotContains(self.client.get(reverse("feed")), "Rude post")

    # --- deleting keeps evidence for 30 days ------------------------------------------
    def test_people_cannot_delete_other_peoples_posts_and_moderator_deletes_are_logged(self):
        post = Post.objects.create(author=self.bob, body="Bob's post")
        self.assertEqual(self.client.post(reverse("post_delete", args=[post.pk])).status_code, 403)
        self.client.force_login(self.mod)
        self.client.post(reverse("post_delete", args=[post.pk]))
        post.refresh_from_db()
        self.assertEqual(post.deleted_by, self.mod)
        self.assertFalse(Post.objects.visible().exists())
        self.assertIn("moderator", LogEntry.objects.get(object_id=str(post.pk)).change_message)

    def test_deleted_posts_are_kept_30_days_unless_under_report_then_removed_with_files(self):
        att = self.photo_post()
        post, storage, name = att.post, att.file.storage, att.file.name
        Report.objects.create(reporter=self.bob, post=post, reason="Harassment")
        self.client.post(reverse("post_delete", args=[post.pk]))  # the author tries to remove the evidence
        self.assertNotContains(self.client.get(reverse("feed")), f'id="post-{post.pk}"')
        self.assertTrue(storage.exists(name))

        Post.objects.filter(pk=post.pk).update(deleted_at=timezone.now() - timedelta(days=31))
        call_command("purge", stdout=StringIO())
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())  # open report: kept

        Report.objects.update(resolved_at=timezone.now())
        call_command("purge", stdout=StringIO())
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.assertFalse(storage.exists(name))

    def test_moderators_can_restore_a_deleted_post(self):
        post = Post.objects.create(author=self.bob, body="Oops", deleted_at=timezone.now(), deleted_by=self.bob)
        self.client.force_login(self.mod)
        self.client.post(reverse("admin:hub_post_changelist"), {"action": "restore", "_selected_action": [post.pk]})
        self.assertTrue(Post.objects.visible().filter(pk=post.pk).exists())

    # --- retention -------------------------------------------------------------------
    @override_settings(LEAVER_RETENTION_DAYS=30)
    def test_retention_removes_old_alerts_and_counts_from_the_day_someone_left(self):
        old = Notification.objects.create(recipient=self.alice, message="old", url="/")
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=91))
        long_ago = timezone.now() - timedelta(days=200)
        Post.objects.create(author=self.bob, body="Bob's last post")
        # Carol last signed in long ago, but only left today: she must not be deleted yet.
        carol = make_user("carol", last_login=long_ago)
        carol.is_active = False
        carol.save(update_fields=["is_active"])
        self.assertIsNotNone(User.objects.get(pk=carol.pk).deactivated_at)
        User.objects.filter(pk=self.bob.pk).update(is_active=False, last_login=long_ago, deactivated_at=long_ago)
        call_command("purge", stdout=StringIO())
        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.bob.pk).exists())
        self.assertFalse(Post.objects.filter(body="Bob's last post").exists())
        self.assertTrue(User.objects.filter(pk=carol.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())
        carol.is_active = True  # back from leave: the date is cleared
        carol.save()
        self.assertIsNone(User.objects.get(pk=carol.pk).deactivated_at)

    def test_people_can_download_their_data(self):
        self.photo_post()
        Post.objects.create(author=self.alice, body="Hello from Alice")
        response = self.client.get(reverse("export_my_data"))
        archive = zipfile.ZipFile(BytesIO(b"".join(response.streaming_content)))
        data = json.loads(archive.read("my-data.json"))
        self.assertEqual(data["profile"]["email"], "alice@example.com")
        self.assertIn("Hello from Alice", [p["text"] for p in data["posts"]])
        self.assertTrue(any(name.startswith("files/") for name in archive.namelist()))

    # --- activity limits and disk space ---------------------------------------------------
    def test_activity_limits_stop_floods(self):
        Post.objects.bulk_create(Post(author=self.alice, body=f"post {i}") for i in range(20))
        response = self.client.post(reverse("feed"), {"body": "one too many"})
        self.assertContains(response, "a lot in a short time")
        self.assertEqual(Post.objects.filter(author=self.alice).count(), 20)

        post = Post.objects.create(author=self.bob, body="Busy thread")
        Comment.objects.bulk_create(Comment(post=post, author=self.alice, body="hi") for _ in range(60))
        response = self.client.post(reverse("comment_create", args=[post.pk]), {"body": "more"}, HTTP_X_FRAGMENT="1")
        self.assertEqual(response.status_code, 429)

    def test_uploads_pause_and_admins_are_emailed_when_the_disk_fills(self):
        with mock.patch("hub.media.disk_free_share", return_value=0.01):
            response = self.client.post(reverse("feed"), {"body": "", "files": [jpeg_with_exif((50, 50))]})
        self.assertContains(response, "nearly full")
        with override_settings(ADMINS=[("IT", "it@example.com")]), mock.patch(
            "hub.management.commands.check_disk.disk_free_share", return_value=0.1
        ):
            call_command("check_disk", stdout=StringIO())
        self.assertEqual(mail.outbox[0].to, ["it@example.com"])

    # --- leavers ---------------------------------------------------------------------
    def run_directory_sync(self, directory, *args, error=None):
        token = mock.Mock(**{"json.return_value": {"access_token": "t"}})
        page = mock.Mock(**{"json.return_value": {"value": directory}})
        out = StringIO()
        with mock.patch("hub.management.commands.sync_directory.requests") as requests, override_settings(
            OIDC_OP_TOKEN_ENDPOINT="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            OIDC_RP_CLIENT_ID="id",
            OIDC_RP_CLIENT_SECRET="secret",
            ADMINS=[("IT", "it@example.com")],
        ):
            requests.RequestException = real_requests.RequestException
            requests.post.return_value, requests.get.return_value = token, page
            requests.get.side_effect = error
            call_command("sync_directory", *args, stdout=out)
        return out.getvalue()

    def test_directory_sync_switches_off_leavers_only(self):
        stayer = User.objects.create_user("stayer", "stayer@example.com")  # single sign-on accounts have no password
        leaver = User.objects.create_user("leaver", "leaver@example.com")
        disabled = User.objects.create_user("disabled", "disabled@example.com")
        renamed = User.objects.create_user("renamed", "old.name@example.com", sso_id="oid-7")
        self.run_directory_sync(
            [
                {"id": "oid-1", "mail": "Stayer@example.com", "accountEnabled": True},
                {"id": "oid-2", "mail": "disabled@example.com", "accountEnabled": False},
                {"id": "oid-7", "mail": "new.name@example.com", "accountEnabled": True},
            ]
        )
        for person, active in [(stayer, True), (leaver, False), (disabled, False), (renamed, True), (self.alice, True)]:
            person.refresh_from_db()
            self.assertEqual(person.is_active, active, person.username)  # alice has a password: left alone
        self.assertIsNotNone(leaver.deactivated_at)

    def test_directory_sync_refuses_to_lock_out_most_of_the_company_and_tells_it(self):
        for i in range(10):
            User.objects.create_user(f"sso{i}", f"sso{i}@example.com")
        directory = [{"id": "x", "mail": "sso0@example.com", "accountEnabled": True}]
        output = self.run_directory_sync(directory, "--dry-run")  # a dry run still lists who would go
        self.assertIn("Would switch off: sso9@example.com", output)
        with self.assertRaises(CommandError):
            self.run_directory_sync(directory)
        self.assertEqual(User.objects.filter(is_active=False).count(), 0)
        self.assertIn("leaver check failed", mail.outbox[-1].subject)

    def test_directory_sync_failure_emails_the_admins(self):
        with self.assertRaises(CommandError):
            self.run_directory_sync([], error=real_requests.ConnectionError("Graph is down"))
        self.assertIn("Graph is down", mail.outbox[-1].body)

    # --- reactions, comments, notifications ------------------------------------------
    def test_reactions_toggle_and_notify_the_author_once(self):
        post = Post.objects.create(author=self.bob, body="Cake in the kitchen")
        url = reverse("react", args=[post.pk])
        self.client.post(url, {"kind": "love"})
        self.assertEqual(Reaction.objects.get().kind, "love")
        self.client.post(url, {"kind": "like"})
        self.assertEqual(Reaction.objects.get().kind, "like")
        self.client.post(url, {"kind": "like"})
        self.assertFalse(Reaction.objects.exists())
        self.client.post(url, {"kind": "like"})  # on again: no second alert
        self.assertEqual(self.bob.notifications.count(), 1)
        self.assertEqual(self.client.post(url, {"kind": "angry"}).status_code, 400)

    def test_busy_posts_send_each_person_one_unread_alert(self):
        post = Post.objects.create(author=self.bob, body="Welcome, everyone!")
        url = reverse("comment_create", args=[post.pk])
        for person in [self.alice, self.mod, make_user("carol"), make_user("dave")]:
            self.client.force_login(person)
            self.client.post(url, {"body": "Welcome!"})
        self.assertEqual(self.bob.notifications.count(), 1)  # not four
        self.assertEqual(self.alice.notifications.count(), 1)  # not three
        self.alice.notifications.update(read_at=timezone.now())
        self.client.post(url, {"body": "One more"})
        self.assertEqual(self.alice.notifications.count(), 2)  # read the first, so she hears about new ones

    def test_event_deletions_are_logged(self):
        event = Event.objects.create(title="Quiz", starts_at=timezone.now() + timedelta(days=1), created_by=self.bob)
        self.client.force_login(self.mod)
        self.client.post(reverse("event_delete", args=[event.pk]))
        self.assertFalse(Event.objects.exists())
        entry = LogEntry.objects.get(object_repr="Quiz")
        self.assertTrue(entry.is_deletion())
        self.assertIn("moderator", entry.change_message)

    def test_comment_returns_updated_card_for_the_page_script(self):
        post = Post.objects.create(author=self.bob, body="Lunch?")
        response = self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Yes please"}, HTTP_X_FRAGMENT="1")
        self.assertContains(response, "Yes please")
        self.assertContains(response, f'id="post-{post.pk}"')
        self.assertEqual(self.bob.notifications.get().message, "Alice commented on your post")

    def test_reports_reach_moderators_who_can_hide_and_close_them(self):
        post = Post.objects.create(author=self.bob, body="Bad joke")
        self.client.post(reverse("report", args=["post", post.pk]), {"reason": "Offensive"})
        report = Report.objects.get()
        self.assertEqual(report.post, post)
        self.assertEqual(self.mod.notifications.count(), 1)
        self.client.force_login(self.mod)
        self.client.post(
            reverse("admin:hub_report_changelist"),
            {"action": "hide_and_resolve", "_selected_action": [report.pk]},
        )
        post.refresh_from_db()
        report.refresh_from_db()
        self.assertTrue(post.is_hidden)
        self.assertIsNotNone(report.resolved_at)

    def test_daily_digest_emails_once(self):
        Notification.objects.create(recipient=self.bob, actor=self.alice, message="Alice said hi", url="/")
        call_command("send_digests", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Alice said hi", mail.outbox[0].body)
        call_command("send_digests", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    # --- groups and events --------------------------------------------------------
    def test_group_event_notifies_members_and_exports_to_calendar(self):
        group = Community.objects.create(name="Book Club", slug="book-club")
        group.members.add(self.alice, self.bob)
        starts = timezone.now() + timedelta(days=3)
        response = self.client.post(
            reverse("event_create"),
            {"title": "Chat, books", "starts_at": starts.strftime("%Y-%m-%dT%H:%M"), "community": group.pk},
        )
        event = Event.objects.get()
        self.assertRedirects(response, event.get_absolute_url())
        self.assertEqual(self.bob.notifications.count(), 1)
        self.assertEqual(RSVP.objects.get().user, self.alice)
        ics = self.client.get(reverse("event_ics", args=[event.pk])).content.decode()
        self.assertIn("SUMMARY:Chat\\, books", ics)
        self.assertIn("DTSTART:", ics)

    def test_rsvp_updates_in_place(self):
        event = Event.objects.create(title="Party", starts_at=timezone.now() + timedelta(days=1), created_by=self.bob)
        self.client.post(reverse("rsvp", args=[event.pk]), {"status": "maybe"})
        self.client.post(reverse("rsvp", args=[event.pk]), {"status": "going"})
        self.assertEqual(RSVP.objects.get().status, "going")

    def test_group_slugs_never_clash_with_the_new_group_page(self):
        self.client.post(reverse("community_create"), {"name": "New"})
        self.assertEqual(Community.objects.get().slug, "new-2")

    def test_pages_render(self):
        Post.objects.create(author=self.bob, body="Hi")
        Comment.objects.create(post=Post.objects.get(), author=self.alice, body="Hello")
        event = Event.objects.create(title="Quiz", starts_at=timezone.now() + timedelta(days=1), created_by=self.bob)
        group = Community.objects.create(name="Quiz Team", slug="quiz-team")
        for url in [
            reverse("feed"), reverse("people") + "?q=bob", reverse("profile", args=[self.bob.pk]),
            reverse("profile_edit"), reverse("communities"), group.get_absolute_url(), reverse("events"),
            reverse("events") + "?past=1", event.get_absolute_url(), reverse("notifications"),
            reverse("post_detail", args=[Post.objects.get().pk]), reverse("event_create"), reverse("community_create"),
            reverse("house_rules"),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
