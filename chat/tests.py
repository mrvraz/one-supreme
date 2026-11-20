import os
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from hub import plugins
from hub.models import Report, User
from hub.security import LIMITS

from . import hooks
from .models import Conversation, Membership, Message

TEMP_MEDIA = tempfile.mkdtemp()


def make_user(name, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)
    return User.objects.create_user(name, f"{name}@example.com", "pw", first_name=name.title(), **extra)


def picture():
    buf = BytesIO()
    Image.new("RGB", (60, 40), "blue").save(buf, "JPEG")
    return SimpleUploadedFile("desk.jpg", buf.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ChatTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.carol = make_user("carol")
        self.mod = make_user("mod", is_staff=True, is_superuser=True)
        self.client.force_login(self.alice)

    def chat_with(self, me, person):
        self.client.force_login(me)
        response = self.client.get(reverse("chat:with", args=[person.pk]))
        return Conversation.objects.get(pk=response["Location"].rstrip("/").rsplit("/", 1)[1])

    def send(self, me, chat, body="", **extra):
        self.client.force_login(me)
        return self.client.post(reverse("chat:send", args=[chat.pk]), {"body": body, **extra})

    def group(self, name="Night shift"):
        """A group chat created by Alice with Bob and Carol."""
        self.client.force_login(self.alice)
        data = {"name": name, "members": [self.bob.pk, self.carol.pk], "create": "1"}
        self.client.post(reverse("chat:new") + "?group=1", data)
        return Conversation.objects.get(name=name)

    # --- access -------------------------------------------------------------------
    def test_only_members_can_read_poll_send_or_open_pictures(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "Just for Bob", image=picture())
        message = Message.objects.get()
        picture_url = reverse("media", args=[message.image.name])
        self.assertEqual(self.client.get(picture_url).status_code, 200)

        self.client.force_login(self.carol)
        self.assertEqual(self.client.get(reverse("chat:thread", args=[chat.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("chat:poll", args=[chat.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("chat:send", args=[chat.pk]), {"body": "Hi"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("chat:mute", args=[chat.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("chat:report", args=[message.pk]), {"reason": "x"}).status_code, 404)
        self.assertEqual(self.client.get(picture_url).status_code, 404)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(Report.objects.count(), 0)

        self.client.logout()
        self.assertEqual(self.client.get(reverse("chat:list")).status_code, 302)

    def test_writes_must_be_posts(self):
        chat = self.chat_with(self.alice, self.bob)
        for name in ["send", "mute", "leave"]:
            self.assertEqual(self.client.get(reverse(f"chat:{name}", args=[chat.pk])).status_code, 405, name)

    # --- one-to-one chats -----------------------------------------------------------
    def test_one_chat_per_pair_and_none_with_yourself_or_leavers(self):
        first = self.chat_with(self.alice, self.bob)
        self.assertEqual(self.chat_with(self.alice, self.bob), first)
        self.assertEqual(self.chat_with(self.bob, self.alice), first)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(first.memberships.count(), 2)

        self.assertEqual(self.client.get(reverse("chat:with", args=[self.bob.pk])).status_code, 404)  # Bob himself
        self.carol.is_active = False
        self.carol.save()
        self.assertEqual(self.client.get(reverse("chat:with", args=[self.carol.pk])).status_code, 404)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_empty_chats_stay_out_of_the_list_until_someone_writes(self):
        chat = self.chat_with(self.alice, self.bob)
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse("chat:list")), "Start messaging")
        self.send(self.alice, chat, "Hello **Bob**")
        self.client.force_login(self.bob)
        response = self.client.get(reverse("chat:list"))
        self.assertNotContains(response, "Start messaging")
        self.assertContains(response, "Hello Bob")  # the preview is plain text
        self.assertContains(response, 'aria-label="1 unread"')

    # --- sending ----------------------------------------------------------------------
    def test_messages_are_escaped_and_formatted(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "<script>alert(1)</script> **bold**")
        response = self.client.get(reverse("chat:thread", args=[chat.pk]))
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt; <strong>bold</strong>")
        self.assertNotContains(response, "<script>alert(1)")

    def test_empty_and_overlong_messages_and_non_pictures_are_refused(self):
        chat = self.chat_with(self.alice, self.bob)
        url = reverse("chat:send", args=[chat.pk])
        self.assertEqual(self.client.post(url, {"body": "  "}, HTTP_X_FRAGMENT="1").status_code, 400)
        self.assertEqual(self.client.post(url, {"body": "x" * 4001}, HTTP_X_FRAGMENT="1").status_code, 400)
        fake = SimpleUploadedFile("notes.jpg", b"not a picture", content_type="image/jpeg")
        response = self.client.post(url, {"body": "", "image": fake}, HTTP_X_FRAGMENT="1")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), 0)
        self.assertRedirects(self.client.post(url, {"body": ""}), chat.get_absolute_url())  # without the page script

    def test_sending_alerts_once_per_unread_streak_and_respects_mute(self):
        chat = self.chat_with(self.alice, self.bob)
        url = chat.get_absolute_url()
        self.send(self.alice, chat, "One")
        self.send(self.alice, chat, "Two")
        alert = self.bob.notifications.get()
        self.assertEqual((alert.message, alert.url, alert.category), ("Alice sent you a message", url, "messages"))
        self.assertEqual(self.alice.notifications.count(), 0)

        self.client.force_login(self.bob)
        self.client.get(url)  # opening the chat marks the alert read
        self.assertIsNotNone(self.bob.notifications.get().read_at)
        self.send(self.alice, chat, "Three")
        self.assertEqual(self.bob.notifications.count(), 2)

        self.client.force_login(self.bob)
        self.client.get(url)
        self.client.post(reverse("chat:mute", args=[chat.pk]))
        self.send(self.alice, chat, "Four")
        self.assertEqual(self.bob.notifications.count(), 2)
        self.client.force_login(self.bob)
        self.client.post(reverse("chat:mute", args=[chat.pk]))  # unmute
        self.send(self.alice, chat, "Five")
        self.assertEqual(self.bob.notifications.count(), 3)

    def test_group_alerts_name_the_group(self):
        chat = self.group()
        self.send(self.bob, chat, "Who is in tonight?")
        self.assertEqual(self.alice.notifications.get().message, "Bob wrote in Night shift")
        self.assertEqual(self.carol.notifications.count(), 1)
        self.assertEqual(self.bob.notifications.count(), 0)

    def test_rate_limit(self):
        chat = self.chat_with(self.alice, self.bob)
        Message.objects.bulk_create(Message(conversation=chat, sender=self.alice, body="hi") for _ in range(LIMITS["message"][0]))
        response = self.send(self.alice, chat, "One too many")
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "a lot in a short time", status_code=429)
        self.assertFalse(Message.objects.filter(body="One too many").exists())

    # --- unread ---------------------------------------------------------------------
    def test_unread_badge_counts_unmuted_chats_with_new_messages(self):
        badge = plugins.NAV_BADGES["chat"]
        with_alice = self.chat_with(self.alice, self.bob)
        with_carol = self.chat_with(self.carol, self.bob)
        self.send(self.alice, with_alice, "One")
        self.send(self.alice, with_alice, "Two")
        self.send(self.carol, with_carol, "Three")
        self.assertEqual(badge(self.bob), 2)  # chats, not messages
        self.assertEqual(badge(self.alice), 0)  # my own messages are never unread

        self.client.force_login(self.bob)
        response = self.client.get(reverse("chat:list"))  # every page gets the badge from hub.context_processors
        self.assertEqual(response.context["nav_badges"]["chat"], 2)
        self.client.get(with_alice.get_absolute_url())
        self.assertEqual(badge(self.bob), 1)
        self.client.post(reverse("chat:mute", args=[with_carol.pk]))
        self.assertEqual(badge(self.bob), 0)

    # --- polling ----------------------------------------------------------------------
    def test_poll_returns_only_newer_messages_and_marks_them_read(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "First")
        first = Message.objects.get()
        self.send(self.alice, chat, "Second")
        self.client.force_login(self.bob)
        data = self.client.get(reverse("chat:poll", args=[chat.pk]), {"after": first.pk}).json()
        self.assertIn("Second", data["html"])
        self.assertNotIn("First", data["html"])
        self.assertEqual(data["last_id"], Message.objects.latest("pk").pk)
        self.assertEqual(plugins.NAV_BADGES["chat"](self.bob), 0)

        with self.assertNumQueries(4):  # nothing new: session, user, membership and messages; no page-wide badge counts
            data = self.client.get(reverse("chat:poll", args=[chat.pk]), {"after": data["last_id"]}).json()
        self.assertEqual((data["html"].strip(), data["last_id"]), ("", Message.objects.latest("pk").pk))
        for odd in ("x", "²"):  # "²" passes isdigit() but int() refuses it
            self.assertEqual(self.client.get(reverse("chat:poll", args=[chat.pk]), {"after": odd}).status_code, 200)

    def test_older_messages_have_no_message_box_so_they_are_not_pulled_back_to_the_newest(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "Hello")
        older = self.client.get(chat.get_absolute_url(), {"before": Message.objects.get().pk + 1})
        self.assertNotContains(older, "chat-composer")  # chat.js only checks for new messages next to the box
        self.assertContains(older, "Latest messages")
        self.assertContains(self.client.get(chat.get_absolute_url()), "chat-composer")

    # --- deleting and reporting -------------------------------------------------------
    def test_people_delete_only_their_own_messages_and_the_picture_is_blocked(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "Oops", image=picture())
        message = Message.objects.get()
        picture_url = reverse("media", args=[message.image.name])
        delete = reverse("chat:delete_message", args=[message.pk])

        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(delete).status_code, 404)
        self.assertIsNone(Message.objects.get().deleted_at)

        self.client.force_login(self.alice)
        self.assertRedirects(self.client.post(delete), chat.get_absolute_url())
        self.assertIsNotNone(Message.objects.get().deleted_at)
        response = self.client.get(chat.get_absolute_url())
        self.assertContains(response, "Message deleted")
        self.assertNotContains(response, "Oops")
        self.assertEqual(self.client.get(picture_url).status_code, 404)
        self.assertEqual(plugins.NAV_BADGES["chat"](self.bob), 0)

    def test_report_quotes_the_real_message_and_reaches_moderators(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.bob, chat, "Something rude")
        message = Message.objects.get()
        self.client.force_login(self.alice)
        with self.assertLogs("hub.security", "INFO") as logs:
            self.client.post(
                reverse("chat:report", args=[message.pk]), {"reason": "This upset me", "body": "He said something worse"}
            )
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.person), (self.alice, self.bob))
        self.assertTrue(report.reason.startswith('"Something rude"'))
        self.assertTrue(report.reason.endswith("This upset me"))
        self.assertNotIn("something worse", report.reason)
        self.assertEqual(self.mod.notifications.get().url, reverse("admin:hub_report_change", args=[report.pk]))
        self.assertIn("chat_message_reported", [record.getMessage() for record in logs.records])

        self.client.post(reverse("chat:report", args=[message.pk]), {"reason": "  "})  # no reason, no report
        self.client.force_login(self.bob)  # and nobody reports their own message
        self.assertEqual(self.client.post(reverse("chat:report", args=[message.pk]), {"reason": "x"}).status_code, 404)
        self.assertEqual(Report.objects.count(), 1)

    # --- group chats ------------------------------------------------------------------
    def test_group_needs_a_name_and_two_other_members(self):
        url = reverse("chat:new") + "?group=1"
        response = self.client.post(url, {"name": "Duo", "members": [self.bob.pk], "create": "1"})
        self.assertContains(response, "at least 2 colleagues")
        self.assertContains(response, "checked")  # Bob stays ticked
        self.client.post(url, {"name": "", "members": [self.bob.pk, self.carol.pk], "create": "1"})
        self.client.post(url, {"name": "Search only", "members": [self.bob.pk, self.carol.pk], "search": "1", "q": "bob"})
        self.assertEqual(Conversation.objects.count(), 0)

        chat = self.group()
        self.assertTrue(chat.is_group)
        self.assertEqual(set(chat.memberships.values_list("user", flat=True)), {self.alice.pk, self.bob.pk, self.carol.pk})
        self.client.force_login(self.carol)  # shown to members straight away, before any message
        self.assertContains(self.client.get(reverse("chat:list")), "Night shift")

    def test_only_the_creator_adds_and_removes_members_and_anyone_can_leave(self):
        chat = self.group()
        dave = make_user("dave")
        members = reverse("chat:members", args=[chat.pk])

        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(members, {"add": dave.pk}).status_code, 403)
        self.assertEqual(self.client.post(members, {"remove": self.carol.pk}).status_code, 403)
        self.client.force_login(dave)
        self.assertEqual(self.client.get(members).status_code, 404)

        self.client.force_login(self.alice)
        self.client.post(members, {"add": dave.pk})
        self.client.post(members, {"remove": self.carol.pk})
        self.client.post(members, {"remove": self.alice.pk})  # the creator leaves with "Leave group" instead
        self.assertEqual(set(chat.memberships.values_list("user", flat=True)), {self.alice.pk, self.bob.pk, dave.pk})
        self.client.force_login(self.carol)
        self.assertEqual(self.client.get(chat.get_absolute_url()).status_code, 404)

        self.client.force_login(self.bob)
        self.assertRedirects(self.client.post(reverse("chat:leave", args=[chat.pk])), reverse("chat:list"))
        self.assertFalse(chat.memberships.filter(user=self.bob).exists())
        one_to_one = self.chat_with(self.alice, dave)
        self.assertEqual(self.client.post(reverse("chat:leave", args=[one_to_one.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("chat:members", args=[one_to_one.pk])).status_code, 404)

    def test_a_group_goes_when_its_last_member_leaves(self):
        chat = self.group()
        self.send(self.alice, chat, "Bye", image=picture())
        path = Message.objects.get().image.path
        for person in [self.alice, self.bob, self.carol]:
            self.client.force_login(person)
            self.client.post(reverse("chat:leave", args=[chat.pk]))
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_when_the_manager_leaves_the_longest_standing_member_takes_over(self):
        chat = self.group()  # Alice started it with Bob and Carol
        User.objects.filter(pk=self.bob.pk).update(is_active=False)  # Bob has left the company
        self.client.force_login(self.alice)
        self.client.post(reverse("chat:leave", args=[chat.pk]))
        chat.refresh_from_db()
        self.assertEqual(chat.created_by, self.carol)
        self.client.force_login(self.carol)
        self.client.post(reverse("chat:members", args=[chat.pk]), {"add": self.alice.pk})
        self.assertTrue(chat.memberships.filter(user=self.alice).exists())

    def test_when_the_manager_leaves_the_company_the_longest_standing_member_manages(self):
        chat = self.group()  # Alice started it with Bob and Carol
        dave = make_user("dave")
        User.objects.filter(pk=self.alice.pk).update(is_active=False)  # Alice left the company without leaving the chat
        self.client.force_login(self.bob)
        self.client.post(reverse("chat:members", args=[chat.pk]), {"add": dave.pk})
        self.assertTrue(chat.memberships.filter(user=dave).exists())

    def test_people_added_later_see_only_what_was_said_after_they_joined(self):
        chat = self.group()
        members = reverse("chat:members", args=[chat.pk])
        self.send(self.alice, chat, "Before Carol was removed")
        self.client.post(members, {"remove": self.carol.pk})
        self.send(self.alice, chat, "About Carol", image=picture())
        # Everything so far a minute earlier, in the same order, so it is clearly before she is back.
        Message.objects.update(created_at=F("created_at") - timedelta(minutes=1))
        Membership.objects.update(joined_at=F("joined_at") - timedelta(minutes=1))
        self.client.post(members, {"add": self.carol.pk})
        self.send(self.alice, chat, "Welcome back")

        self.client.force_login(self.carol)
        page = self.client.get(chat.get_absolute_url())
        self.assertContains(page, "Welcome back")
        self.assertNotContains(page, "About Carol")
        self.assertNotContains(page, "Before Carol was removed")
        self.assertNotIn("About Carol", self.client.get(reverse("chat:poll", args=[chat.pk])).json()["html"])
        name = Message.objects.get(body="About Carol").image.name
        self.assertEqual(self.client.get(reverse("media", args=[name])).status_code, 404)
        self.assertTrue(hooks.can_open_picture(self.bob, name))  # Bob was there

    # --- clean-up and data export -------------------------------------------------------
    def test_purger_removes_old_deleted_messages_and_their_pictures(self):
        self.assertIn(hooks.purge, plugins.PURGERS)
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "Old and deleted", image=picture())
        now = timezone.now()
        old = Message.objects.get()
        path = old.image.path
        Message.objects.filter(pk=old.pk).update(deleted_at=now - timedelta(days=31))
        Message.objects.create(conversation=chat, sender=self.alice, body="Just deleted", deleted_at=now - timedelta(days=2))
        Message.objects.create(conversation=chat, sender=self.alice, body="Last year", created_at=now - timedelta(days=400))
        self.assertTrue(os.path.exists(path))

        self.assertEqual(hooks.purge(now), ("chat messages", 1))
        self.assertFalse(os.path.exists(path))
        self.assertEqual(set(Message.objects.values_list("body", flat=True)), {"Just deleted", "Last year"})
        with override_settings(CHAT_RETENTION_DAYS=365):
            self.assertEqual(hooks.purge(now), ("chat messages", 1))
        self.assertEqual(Message.objects.get().body, "Just deleted")

    def test_a_reported_picture_is_kept_and_moderators_can_open_it(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "Look", image=picture())
        message = Message.objects.get()
        name = message.image.name
        self.assertFalse(hooks.can_open_picture(self.mod, name))  # nobody has reported Alice yet
        self.client.force_login(self.bob)
        self.client.post(reverse("chat:report", args=[message.pk]), {"reason": "Not OK"})
        self.assertTrue(hooks.can_open_picture(self.mod, name))
        self.assertFalse(hooks.can_open_picture(self.carol, name))
        admin_page = self.client_for(self.mod).get(reverse("admin:hub_report_changelist"))
        self.assertContains(admin_page, f'href="{settings.MEDIA_URL}{name}"')

        # Alice deletes it, and 31 days pass with the report still open: the picture stays as evidence.
        Message.objects.filter(pk=message.pk).update(deleted_at=timezone.now() - timedelta(days=31))
        self.assertEqual(hooks.purge(timezone.now()), ("chat messages", 0))
        self.assertTrue(hooks.can_open_picture(self.mod, name))
        Report.objects.update(resolved_at=timezone.now())
        self.assertEqual(hooks.purge(timezone.now()), ("chat messages", 1))

    def client_for(self, user):
        self.client.force_login(user)
        return self.client

    def test_exporter_lists_my_messages_and_pictures(self):
        self.assertIn(hooks.export, plugins.EXPORTERS)
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.alice, chat, "From Alice", image=picture())
        self.send(self.bob, chat, "From Bob")
        group = self.group()
        self.send(self.alice, group, "To the team")

        key, data, files = hooks.export(self.alice)
        self.assertEqual(key, "chat")
        self.assertEqual([(m["conversation"], m["text"]) for m in data], [("Bob", "From Alice"), ("Night shift", "To the team")])
        self.assertIsNotNone(data[0]["time"])
        self.assertEqual(files, [Message.objects.get(body="From Alice").image.path])
        self.assertTrue(os.path.isfile(files[0]))

    # --- pages ------------------------------------------------------------------------
    def test_pages_render(self):
        chat = self.chat_with(self.alice, self.bob)
        self.send(self.bob, chat, "Hello", image=picture())
        group = self.group()
        self.send(self.bob, group, "Hi all")
        self.client.force_login(self.alice)
        for url in [
            reverse("chat:list"), reverse("chat:new"), reverse("chat:new") + "?q=bob", reverse("chat:new") + "?group=1",
            chat.get_absolute_url(), group.get_absolute_url(), group.get_absolute_url() + "?before=1",
            reverse("chat:members", args=[group.pk]) + "?q=mod",
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        response = self.client.get(group.get_absolute_url())
        self.assertContains(response, "chat/chat.js")
        self.assertContains(response, "Leave group")
        self.assertContains(response, "Bob</a>")  # the sender's name, in group chats
