"""Tests for the features from the app review: news, polls, pins, replies, mentions, scheduling, private groups,
organisation units, birthdays, notification choices, do not disturb, push, reminders, search and translation."""

import json
import logging
import shutil
import struct
import tempfile
import zlib
from datetime import date, datetime, time, timedelta
from io import BytesIO, StringIO
from unittest import mock

import requests
from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.log import AdminEmailHandler
from PIL import Image as PILImage

from . import push
from .models import (
    REMINDER_CHOICES, RSVP, Comment, CommentReaction, Community, Event, GroupInvite, Notification, PollOption, PollVote,
    Post, PostRead, PushSubscription, Report, User, notify,
)
from .tasks import publish_due, send_reminders

TEMP_MEDIA = tempfile.mkdtemp()
FORMAT = "%Y-%m-%dT%H:%M"  # what the browser's date-and-time picker sends


def make_user(name, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)
    extra.setdefault("first_name", name.title())
    extra.setdefault("last_name", "Test")
    return User.objects.create_user(name, f"{name}@example.com", "pw", **extra)


@override_settings(MEDIA_ROOT=TEMP_MEDIA, ALLOW_PASSWORD_LOGIN=True)
class FeatureTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice, self.bob, self.carol = make_user("alice"), make_user("bob"), make_user("carol")
        self.mod = make_user("mod", is_staff=True, is_superuser=True)
        self.client.force_login(self.alice)

    def make_post(self, author, body, **extra):
        return Post.objects.create(author=author, body=body, notified_at=timezone.now(), **extra)

    def allow(self, user, codename):
        user.user_permissions.add(Permission.objects.get(codename=codename))

    # --- news -----------------------------------------------------------------
    def test_only_publishers_write_news(self):
        self.assertEqual(self.client.get(reverse("news_new")).status_code, 403)
        self.allow(self.alice, "publish_news")
        self.assertEqual(self.client.get(reverse("news_new")).status_code, 200)

    def test_news_reaches_only_its_audience_and_tracks_unread(self):
        self.allow(self.alice, "publish_news")
        team = Community.objects.create(name="Ops", slug="ops", kind=Community.UNIT, unit_type="department")
        team.members.add(self.bob)
        response = self.client.post(reverse("news_new"), {"title": "New rota", "body": "It's up", "audiences": [team.pk]})
        item = Post.objects.get(kind=Post.NEWS)
        self.assertRedirects(response, item.get_absolute_url())
        self.assertTrue(Notification.objects.filter(recipient=self.bob, category="news").exists())
        self.assertFalse(Notification.objects.filter(recipient=self.carol).exists())

        self.client.force_login(self.carol)
        self.assertNotContains(self.client.get(reverse("news")), "New rota")
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)

        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse("news") + "?show=unread"), "New rota")
        self.client.get(item.get_absolute_url())
        self.assertTrue(PostRead.objects.filter(post=item, user=self.bob).exists())
        self.assertNotContains(self.client.get(reverse("news") + "?show=unread"), "New rota")

    def test_must_read_news_shows_its_author_who_confirmed(self):
        self.allow(self.alice, "publish_news")
        must = self.make_post(self.alice, "Read me", kind=Post.NEWS, title="Fire drill", requires_ack=True)
        plain = self.make_post(self.alice, "In the kitchen", kind=Post.NEWS, title="Cake")
        self.client.force_login(self.bob)
        self.client.post(reverse("news_ack", args=[must.pk]))
        self.assertIsNotNone(PostRead.objects.get(post=must, user=self.bob).acknowledged_at)
        self.assertEqual(self.client.post(reverse("news_ack", args=[plain.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("news_readers", args=[must.pk])).status_code, 403)

        self.client.force_login(self.alice)
        response = self.client.get(reverse("news_readers", args=[must.pk]))
        self.assertEqual([person for person, _when in response.context["done"]], [self.bob])
        self.assertIn(self.carol, response.context["waiting"])
        # Ordinary news only ever shows totals: nobody is listed for simply reading it.
        self.assertEqual(self.client.get(reverse("news_readers", args=[plain.pk])).status_code, 404)

    def test_draft_and_scheduled_news_stay_hidden_until_live(self):
        self.allow(self.alice, "publish_news")
        later = (timezone.localtime() + timedelta(hours=2)).strftime(FORMAT)
        self.client.post(reverse("news_new"), {"title": "Party", "body": "Soon", "publish_at": later})
        self.client.post(reverse("news_new"), {"title": "Idea", "body": "Not yet", "draft": "1"})
        scheduled, draft = Post.objects.get(title="Party"), Post.objects.get(title="Idea")
        self.assertTrue(scheduled.is_scheduled)
        self.assertTrue(draft.is_draft)
        self.assertFalse(Notification.objects.exists())
        self.assertContains(self.client.get(reverse("news") + "?show=scheduled"), "Party")

        self.client.force_login(self.bob)
        for item in (scheduled, draft):
            self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("news")), "Party")

    # --- posts: scheduling, polls, pins, replies, mentions -------------------------
    def test_scheduled_posts_go_live_on_time_and_are_announced_once(self):
        later = (timezone.localtime() + timedelta(hours=1)).strftime(FORMAT)
        self.client.post(reverse("feed"), {"body": "Later, @Bob Test", "publish_at": later})
        post = Post.objects.get()
        self.assertTrue(post.is_scheduled)
        self.assertFalse(Notification.objects.exists())
        self.assertContains(self.client.get(reverse("scheduled")), "Later")

        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)
        self.assertEqual(publish_due(), 0)
        Post.objects.filter(pk=post.pk).update(created_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(publish_due(), 1)
        self.assertEqual(publish_due(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.bob, category="mentions").count(), 1)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_polls_take_one_vote_per_person_and_close(self):
        self.client.post(reverse("feed"), {"body": "Lunch?", "poll_options": "Pizza\nSushi"})
        poll = Post.objects.get(kind=Post.POLL)
        pizza, sushi = poll.options.order_by("position")
        self.client.force_login(self.bob)
        vote = reverse("poll_vote", args=[poll.pk])
        self.client.post(vote, {"option": pizza.pk})
        self.client.post(vote, {"option": sushi.pk})  # changing your mind replaces the vote
        self.assertEqual(list(PollVote.objects.values_list("user", "option")), [(self.bob.pk, sushi.pk)])

        other = self.make_post(self.alice, "Other poll", kind=Post.POLL)
        stray = PollOption.objects.create(post=other, text="Elsewhere")
        self.assertEqual(self.client.post(vote, {"option": stray.pk}).status_code, 400)

        Post.objects.filter(pk=poll.pk).update(poll_closes_at=timezone.now() - timedelta(minutes=1))
        self.client.post(vote, {"option": pizza.pk})
        self.assertEqual(PollVote.objects.get(user=self.bob).option, sushi)

    def test_a_poll_must_close_after_it_opens(self):
        past = (timezone.localtime() - timedelta(hours=1)).strftime(FORMAT)
        response = self.client.post(reverse("feed"), {"body": "Lunch?", "poll_options": "A\nB", "poll_closes_at": past})
        self.assertFalse(Post.objects.exists())
        self.assertIn("The poll must close after it opens.", response.context["form"].non_field_errors())

    def test_only_moderators_and_group_admins_pin(self):
        company = self.make_post(self.bob, "For everyone")
        self.assertEqual(self.client.post(reverse("post_pin", args=[company.pk])).status_code, 403)

        club = Community.objects.create(name="Club", slug="club")
        club.members.add(self.alice, self.bob)
        club.admins.add(self.alice)
        in_club = self.make_post(self.bob, "For the club", community=club)
        self.client.post(reverse("post_pin", args=[in_club.pk]))
        self.assertIsNotNone(Post.objects.get(pk=in_club.pk).pinned_at)

        self.client.force_login(self.mod)
        self.client.post(reverse("post_pin", args=[company.pk]))
        self.assertEqual([p.pk for p in self.client.get(reverse("feed")).context["pinned"]], [company.pk])
        self.client.force_login(self.alice)  # in the club: its pin stays on top of the club's page, not of her feed
        self.assertEqual([p.pk for p in self.client.get(reverse("feed")).context["pinned"]], [company.pk])
        self.assertEqual([p.pk for p in self.client.get(club.get_absolute_url()).context["pinned"]], [in_club.pk])

    def test_replies_stay_one_level_deep_and_tell_the_commenter(self):
        post = self.make_post(self.alice, "Hello")
        self.client.force_login(self.bob)
        self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Hi"})
        first = Comment.objects.get()
        self.client.force_login(self.carol)
        self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Reply", "parent": first.pk})
        reply = Comment.objects.latest("pk")
        self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Reply to the reply", "parent": reply.pk})
        deeper = Comment.objects.latest("pk")
        self.assertEqual((reply.parent, deeper.parent), (first, first))
        self.assertTrue(Notification.objects.filter(recipient=self.bob, message__contains="replied to your comment").exists())

        self.client.force_login(self.alice)
        react = reverse("comment_react", args=[first.pk])
        self.client.post(react, {"kind": "love"})
        self.assertEqual(CommentReaction.objects.get().kind, "love")
        self.client.post(react, {"kind": "love"})  # the same reaction again takes it back
        self.assertFalse(CommentReaction.objects.exists())
        self.assertEqual(self.client.post(react, {"kind": "angry"}).status_code, 400)

    def test_mentions_match_whole_names_only(self):
        ann = make_user("ann", last_name="Lee")
        ann_leeson = make_user("annl", first_name="Ann", last_name="Leeson")
        self.client.post(reverse("feed"), {"body": "Thanks @Ann Leeson!"})
        post = Post.objects.get()
        self.assertEqual(list(post.mentions.all()), [ann_leeson])
        self.assertTrue(Notification.objects.filter(recipient=ann_leeson, category="mentions").exists())
        self.assertFalse(Notification.objects.filter(recipient=ann).exists())
        self.assertIn('class="mention"', post.body_html)

    def test_feed_filters_by_scope_and_type(self):
        club = Community.objects.create(name="Club", slug="club")
        club.members.add(self.alice)
        company = self.make_post(self.bob, "For everyone")
        in_club = self.make_post(self.bob, "For the club", community=club)
        poll = self.make_post(self.bob, "A poll", kind=Post.POLL)

        def shown(query):
            return {p.pk for p in self.client.get(reverse("feed") + query).context["posts"]}

        self.assertEqual(shown(""), {company.pk, in_club.pk, poll.pk})
        self.assertEqual(shown("?scope=company"), {company.pk, poll.pk})
        self.assertEqual(shown("?scope=mine"), {in_club.pk})
        self.assertEqual(shown("?type=poll"), {poll.pk})
        self.assertEqual(shown("?scope=nonsense&type=nonsense"), {company.pk, in_club.pk, poll.pk})

    # --- groups and the organisation ------------------------------------------------
    def test_private_groups_need_an_invitation_or_an_approved_request(self):
        board = Community.objects.create(name="Board", slug="board", is_private=True)
        board.members.add(self.alice)
        board.admins.add(self.alice)
        secret = self.make_post(self.alice, "Budget talk", community=board)

        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(board.get_absolute_url()), "Budget talk")
        self.assertEqual(self.client.get(secret.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(reverse("community_members", args=[board.slug])).status_code, 404)
        self.client.post(reverse("community_join", args=[board.slug]))
        self.client.post(reverse("community_join", args=[board.slug]))  # asking twice makes one request
        request = GroupInvite.objects.get()
        self.assertEqual(request.kind, GroupInvite.REQUEST)
        self.assertFalse(board.has_member(self.bob))
        self.assertTrue(Notification.objects.filter(recipient=self.alice, invite=request).exists())
        self.assertEqual(self.client.post(reverse("invite_answer", args=[request.pk]), {"answer": "accept"}).status_code, 403)

        self.client.force_login(self.alice)
        self.client.post(reverse("invite_answer", args=[request.pk]), {"answer": "accept"})
        self.assertTrue(board.has_member(self.bob))
        self.assertTrue(Notification.objects.filter(recipient=self.bob, message__contains="approved").exists())

        # An invitation is answered by the invited person only, and only admins invite.
        self.client.post(reverse("community_invite", args=[board.slug]), {"user": self.carol.pk})
        invite = GroupInvite.objects.get(kind=GroupInvite.INVITE)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse("invite_answer", args=[invite.pk]), {"answer": "accept"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("community_invite", args=[board.slug]), {"user": self.mod.pk}).status_code, 403)
        self.client.force_login(self.carol)
        self.client.post(reverse("invite_answer", args=[invite.pk]), {"answer": "decline"})
        self.assertFalse(board.has_member(self.carol))

    def test_units_are_set_by_admins_not_joined_or_left(self):
        finance = Community.objects.create(name="Finance", slug="finance", kind=Community.UNIT, unit_type="department")
        finance.admins.add(self.alice)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse("community_join", args=[finance.slug])).status_code, 403)
        self.assertEqual(self.client.post(reverse("community_leave", args=[finance.slug])).status_code, 403)
        self.client.force_login(self.alice)
        self.client.post(reverse("community_invite", args=[finance.slug]), {"user": self.bob.pk})
        self.assertTrue(finance.has_member(self.bob))
        self.assertFalse(GroupInvite.objects.exists())

    # --- people -------------------------------------------------------------------
    def test_birthdays_are_opt_in_and_keep_no_year(self):
        today = timezone.localdate()
        self.client.post(reverse("profile_edit"), {"birthday_day": today.day, "birthday_month": today.month})
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.birthday, date(2000, today.month, today.day))
        self.assertEqual([person for _when, person in self.client.get(reverse("birthdays")).context["birthdays"]], [self.alice])
        self.assertIn(self.alice, self.client.get(reverse("feed")).context["birthdays_today"])

        bad = self.client.post(reverse("profile_edit"), {"birthday_day": 31, "birthday_month": 2})
        self.assertIn("That birthday isn't a real date.", bad.context["form"].non_field_errors())

        soon = today + timedelta(days=3 if (today + timedelta(days=3)).strftime("%m%d") != "0229" else 4)
        self.bob.start_date = soon.replace(year=soon.year - 2)
        self.bob.save()
        self.assertEqual(self.client.get(reverse("birthdays")).context["anniversaries"], [(soon, self.bob, 2)])

    # --- notification choices, do not disturb, email and push -------------------------
    def test_notification_settings_store_each_choice(self):
        self.client.post(reverse("settings_notifications"), {"push_privacy": "hidden", "mentions_push": "on", "news_email": "on"})
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.push_privacy, "hidden")
        self.assertTrue(self.alice.wants("mentions", "push"))
        self.assertFalse(self.alice.wants("comments", "push"))
        self.assertTrue(self.alice.wants("news", "email"))
        self.assertFalse(self.alice.wants("mentions", "email"))
        self.assertFalse(self.alice.email_digest)

    def test_quiet_hours_can_run_past_midnight(self):
        self.bob.dnd_from, self.bob.dnd_to = time(22), time(7)
        zone = timezone.get_current_timezone()

        def wednesday(hour):
            return timezone.make_aware(datetime(2026, 11, 11, hour, 30), zone)

        self.assertTrue(self.bob.dnd_active(wednesday(23)))
        self.assertTrue(self.bob.dnd_active(wednesday(6)))
        self.assertFalse(self.bob.dnd_active(wednesday(12)))
        self.bob.dnd_weekends = True
        self.assertTrue(self.bob.dnd_active(timezone.make_aware(datetime(2026, 11, 14, 12), zone)))  # a Saturday

    def test_digest_respects_email_choices_and_do_not_disturb(self):
        self.bob.notify_prefs = {"comments": {"email": False}}
        self.bob.dnd_on = True
        self.bob.save()
        notify([self.bob], self.alice, "Alice commented on your post", "/posts/1/", category="comments")
        notify([self.bob], self.alice, "Alice mentioned you", "/posts/2/", category="mentions")
        call_command("send_digests", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Notification.objects.filter(emailed_at__isnull=False).exists())  # kept for the next digest

        self.bob.dnd_on = False
        self.bob.save()
        call_command("send_digests", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Alice mentioned you", mail.outbox[0].body)
        self.assertNotIn("commented", mail.outbox[0].body)
        self.assertFalse(Notification.objects.filter(emailed_at__isnull=True).exists())

    def test_push_only_accepts_known_push_services(self):
        def subscribe(endpoint):
            data = json.dumps({"endpoint": endpoint, "keys": {"p256dh": "key", "auth": "secret"}})
            return self.client.post(reverse("push_subscribe"), data, content_type="application/json")

        for endpoint in ["https://evil.example.com/x", "http://fcm.googleapis.com/x", "https://fcm.googleapis.com.evil.com/x"]:
            self.assertEqual(subscribe(endpoint).status_code, 400, endpoint)
        self.assertEqual(subscribe("https://fcm.googleapis.com/fcm/send/abc").status_code, 200)
        self.assertEqual(self.alice.push_subscriptions.count(), 1)
        self.assertEqual(self.client.post(reverse("push_subscribe"), "nonsense", content_type="application/json").status_code, 400)

    @override_settings(VAPID_PRIVATE_KEY="test-key")
    def test_push_follows_each_persons_settings_and_drops_dead_devices(self):
        for person in (self.bob, self.carol):
            PushSubscription.objects.create(user=person, endpoint=f"https://fcm.googleapis.com/{person.username}", p256dh="k", auth="a")
        self.carol.push_privacy = "hidden"
        self.carol.save()
        notify([self.bob, self.carol], self.alice, "Alice mentioned you", "/x/", category="mentions")
        notify([self.bob], self.alice, "Alice reacted", "/y/", category="reactions")  # reactions are off for push by default
        Notification.objects.create(recipient=self.bob, message="Old news", url="/z/", created_at=timezone.now() - timedelta(hours=1))
        with mock.patch.object(push, "send_to", return_value=201) as send:
            self.assertEqual(push.send_pending(), 2)
        bodies = {call.args[0].user_id: call.args[1]["body"] for call in send.call_args_list}
        self.assertEqual(bodies, {self.bob.pk: "Alice mentioned you", self.carol.pk: "You have a new notification"})
        self.assertFalse(Notification.objects.filter(pushed_at__isnull=True).exists())

        self.bob.dnd_on = True
        self.bob.save()
        notify([self.bob, self.carol], self.alice, "Alice mentioned you again", "/x/", category="mentions")
        with mock.patch.object(push, "send_to", return_value=410) as send:  # 410: that phone has unsubscribed
            push.send_pending()
        self.assertEqual([call.args[0].user_id for call in send.call_args_list], [self.carol.pk])
        self.assertFalse(PushSubscription.objects.filter(user=self.carol).exists())
        self.assertTrue(PushSubscription.objects.filter(user=self.bob).exists())

    def test_event_reminders_go_out_once_at_the_chosen_time(self):
        now = timezone.now()
        quiz = Event.objects.create(title="Quiz", starts_at=now + timedelta(minutes=60), created_by=self.alice)
        RSVP.objects.create(event=quiz, user=self.bob, status=RSVP.Status.GOING)  # default: a day and an hour before
        RSVP.objects.create(event=quiz, user=self.carol, status=RSVP.Status.DECLINED)
        RSVP.objects.create(event=quiz, user=self.mod, status=RSVP.Status.MAYBE, reminders=[])
        self.assertEqual(send_reminders(now), 1)
        self.assertEqual(send_reminders(now + timedelta(minutes=1)), 0)
        note = Notification.objects.get()
        self.assertEqual((note.recipient, note.category), (self.bob, "events"))
        hour = dict(REMINDER_CHOICES)[60].removesuffix(" before")
        self.assertEqual(note.message, f"Reminder: Quiz starts in {hour}")

    def test_moving_an_event_sends_its_reminders_again_for_the_new_time(self):
        now = timezone.now()
        quiz = Event.objects.create(title="Quiz", starts_at=now + timedelta(minutes=60), created_by=self.alice)
        RSVP.objects.create(event=quiz, user=self.bob, status=RSVP.Status.GOING)  # reminded an hour before
        self.assertEqual(send_reminders(now), 1)
        later = timezone.localtime(now + timedelta(days=7)).replace(second=0, microsecond=0)
        data = {"title": "Quiz", "starts_at": later.strftime(FORMAT), "ends_at": "", "location": "", "community": "", "description": ""}
        self.client.post(reverse("event_edit", args=[quiz.pk]), data)  # Alice organises it
        quiz.refresh_from_db()
        self.assertEqual(quiz.starts_at, later)
        self.assertEqual(send_reminders(later - timedelta(minutes=60)), 1)

    @override_settings(VAPID_PRIVATE_KEY="test-key")
    def test_a_push_service_that_does_not_answer_is_skipped_for_the_rest_of_the_run(self):
        for person in (self.bob, self.carol):
            PushSubscription.objects.create(user=person, endpoint=f"https://fcm.googleapis.com/{person.username}", p256dh="k", auth="a")
        notify([self.bob, self.carol], self.alice, "Alice mentioned you", "/x/", category="mentions")
        with mock.patch.object(push, "send_to", side_effect=requests.ConnectionError("blocked by the firewall")) as send:
            self.assertEqual(push.send_pending(), 0)
        self.assertEqual(send.call_count, 1)  # Carol's phone uses the same service: not tried, so no second wait

    def test_crashes_are_logged_not_emailed(self):
        # Django's default emails every crash to ADMINS, with the form data (someone's post) inside.
        handlers = logging.getLogger("django").handlers + logging.getLogger("django.request").handlers
        self.assertFalse([handler for handler in handlers if isinstance(handler, AdminEmailHandler)])

    def test_a_29_february_birthday_and_a_first_work_anniversary_show_up(self):
        User.objects.filter(pk=self.bob.pk).update(birthday=date(2000, 2, 29))
        User.objects.filter(pk=self.carol.pk).update(start_date=date(2027, 1, 5))
        with mock.patch("django.utils.timezone.localdate", return_value=date(2027, 2, 28)):  # not a leap year
            self.assertIn(self.bob, self.client.get(reverse("feed")).context["birthdays_today"])
        with mock.patch("django.utils.timezone.localdate", return_value=date(2027, 12, 20)):
            anniversaries = self.client.get(reverse("birthdays")).context["anniversaries"]
        self.assertIn((date(2028, 1, 5), self.carol, 1), anniversaries)

    def test_draft_news_covers_and_hidden_comment_photos_stay_private(self):
        draft = self.make_post(self.bob, "Soon", kind=Post.NEWS, title="Soon", is_draft=True)
        draft.cover.save("soon.jpg", ContentFile(b"jpeg"))
        comment = Comment.objects.create(post=self.make_post(self.bob, "Open"), author=self.bob, body="", is_hidden=True)
        comment.image.save("hidden.jpg", ContentFile(b"jpeg"))
        for name in (draft.cover.name, comment.image.name):
            url = reverse("media", args=[name])
            self.client.force_login(self.alice)
            self.assertEqual(self.client.get(url).status_code, 404, name)
            self.client.force_login(self.mod)
            self.assertEqual(self.client.get(url).status_code, 200, name)

    def test_ids_that_are_not_numbers_are_ignored_not_crashed_on(self):
        self.assertEqual(self.client.get(reverse("people") + "?unit=abc").status_code, 200)
        post = self.make_post(self.bob, "Hi")
        self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Hello", "parent": "abc"})
        self.assertTrue(Comment.objects.filter(post=post, body="Hello", parent=None).exists())

    # --- search, translation, insights ---------------------------------------------
    def test_search_never_shows_posts_from_groups_you_cannot_see(self):
        board = Community.objects.create(name="Board", slug="board", is_private=True)
        board.members.add(self.bob)
        self.make_post(self.bob, "Secret budget", community=board)
        self.make_post(self.bob, "Open budget")
        found = dict(self.client.get(reverse("search") + "?q=budget").context["sections"])
        self.assertEqual([title for title, _url, _detail in found["Posts"]], ["Open budget"])
        self.client.force_login(self.bob)
        found = dict(self.client.get(reverse("search") + "?q=budget").context["sections"])
        self.assertEqual(len(found["Posts"]), 2)

    @override_settings(TRANSLATE_URL="")
    def test_translation_is_off_unless_a_server_is_set(self):
        post = self.make_post(self.bob, "Bonjour")
        self.assertEqual(self.client.post(reverse("translate", args=["post", post.pk])).status_code, 404)

    @override_settings(TRANSLATE_URL="http://translate.internal")
    def test_translation_is_escaped_and_uses_the_readers_language(self):
        post = self.make_post(self.bob, "Bonjour")
        answer = mock.Mock(**{"json.return_value": {"translatedText": "Hello <script>"}})
        with mock.patch("hub.views.requests.post", return_value=answer) as sent:
            response = self.client.post(reverse("translate", args=["post", post.pk]))
        self.assertEqual(sent.call_args.kwargs["json"]["target"], self.alice.language)
        self.assertIn("Hello &lt;script&gt;", response.json()["html"])

    def test_usage_figures_need_permission(self):
        self.assertEqual(self.client.get(reverse("insights")).status_code, 403)
        self.allow(self.alice, "view_insights")
        self.assertEqual(self.client.get(reverse("insights")).status_code, 200)

    # --- fixes from the code audit ----------------------------------------------------
    def test_an_unread_alert_of_another_kind_does_not_swallow_a_comment_or_a_mention(self):
        post = self.make_post(self.alice, "The new rota is up")
        notify([self.bob], self.alice, "News: rota", post.get_absolute_url(), category="news")  # Bob hasn't read it
        notify([self.alice], self.carol, "Carol liked your post", post.get_absolute_url(), category="reactions")
        self.client.force_login(self.carol)
        self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Thanks! @Bob Test can you swap?"})
        self.assertTrue(Notification.objects.filter(recipient=self.alice, category="comments").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.bob, category="mentions").exists())

        # Unread comment alerts still collapse: Alice isn't told again about the next comment.
        self.client.force_login(self.bob)
        self.client.post(reverse("comment_create", args=[post.pk]), {"body": "Sure"})
        self.assertEqual(Notification.objects.filter(recipient=self.alice, category="comments").count(), 1)

    @override_settings(NOTIFICATION_RETENTION_DAYS=0, LEAVER_RETENTION_DAYS=30)
    def test_purge_keeps_alerts_at_0_keeps_reported_leavers_and_removes_covers(self):
        notify([self.bob], self.alice, "Hello", "/")
        Notification.objects.update(created_at=timezone.now() - timedelta(days=400))
        reported, gone = make_user("rex", is_active=False), make_user("gwen", is_active=False)
        Report.objects.create(reporter=self.bob, person=reported, reason="Rude in chat")
        gone.cover.save("cover.jpg", ContentFile(b"jpeg"))
        cover = gone.cover.name
        moderator = make_user("moira", is_active=False, is_staff=True)  # hid a post before she left
        LogEntry.objects.create(
            user=moderator, content_type=ContentType.objects.get_for_model(Post), object_id="1", object_repr="A post",
            action_flag=CHANGE,
        )
        leavers = [reported.pk, gone.pk, moderator.pk]
        User.objects.filter(pk__in=leavers).update(deactivated_at=timezone.now() - timedelta(days=40))
        call_command("purge", stdout=StringIO())
        self.assertTrue(LogEntry.objects.filter(user=moderator).exists())  # the moderation log keeps its history
        self.assertEqual(Notification.objects.count(), 1)  # 0 means keep
        self.assertTrue(Report.objects.filter(person=reported).exists())  # the leaver stays while HR looks into it
        self.assertFalse(User.objects.filter(pk=gone.pk).exists())
        self.assertFalse(default_storage.exists(cover))

    def test_the_scheduler_still_runs_hourly_and_daily_jobs_after_a_slow_minute(self):
        from hub.management.commands import scheduler

        # The tick that started at 04:59 ran long, so the loop never saw 05:00.
        clock = [datetime.fromisoformat(f"2026-11-12T{t}+00:00") for t in ("04:58", "04:59", "05:02", "05:03", "06:01")]
        ran = []

        class Stop(Exception):
            pass

        with (
            mock.patch.object(scheduler, "datetime", **{"now.side_effect": clock}),
            mock.patch.object(scheduler, "run", side_effect=lambda name: ran.append(name)),
            mock.patch("time.sleep", side_effect=[None] * (len(clock) - 1) + [Stop]),
            self.assertRaises(Stop),
        ):
            call_command("scheduler", stdout=StringIO())
        self.assertEqual(ran.count("tick"), 5)
        self.assertEqual(ran.count("check_disk"), 3)  # once in each of the hours 04, 05 and 06
        self.assertEqual([job for job in ran if job not in ("tick", "check_disk")], ["send_digests", "sync_directory", "purge"])

    def test_a_photo_with_too_many_pixels_is_refused_before_it_is_unpacked(self):
        from .media import process_upload

        buf = BytesIO()
        PILImage.new("L", (1, 1)).save(buf, "PNG")
        png = bytearray(buf.getvalue())
        header = struct.pack(">II", 9000, 7000) + png[24:29]  # a 1-pixel PNG that claims 63 megapixels
        png[16:33] = header + struct.pack(">I", zlib.crc32(b"IHDR" + header))
        with self.assertRaisesMessage(ValidationError, "megapixels"):
            process_upload(SimpleUploadedFile("big.png", bytes(png), content_type="image/png"))

    def test_a_video_in_a_picture_field_is_refused_before_it_is_converted(self):
        from .media import process_upload

        video = SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100, content_type="video/mp4")
        with mock.patch("hub.media.strip_video") as convert, self.assertRaisesMessage(ValidationError, "not a video"):
            process_upload(video, video=False)
        convert.assert_not_called()

    def test_deleting_a_group_or_a_person_removes_their_photos_from_disk(self):
        group = Community.objects.create(name="Runners", slug="runners")
        group.cover.save("cover.jpg", ContentFile(b"jpeg"))
        self.bob.avatar.save("me.jpg", ContentFile(b"jpeg"))
        files = [group.cover.name, self.bob.avatar.name]
        group.delete()
        self.bob.delete()
        self.assertEqual([default_storage.exists(name) for name in files], [False, False])

    def test_when_the_last_admin_leaves_a_group_the_longest_standing_member_takes_over(self):
        group = Community.objects.create(name="Runners", slug="runners", is_private=True)
        group.members.add(self.alice, self.bob)
        group.members.add(self.carol)
        group.admins.add(self.alice)
        self.client.post(reverse("community_leave", args=[group.slug]))
        self.assertEqual(list(group.admins.all()), [self.bob])
        self.assertTrue(Notification.objects.filter(recipient=self.bob, category="groups").exists())

    def test_moderators_cannot_change_who_a_report_is_about(self):
        report = Report.objects.create(reporter=self.bob, person=self.carol, reason="Rude")
        self.client.force_login(self.mod)
        page = self.client.get(reverse("admin:hub_report_change", args=[report.pk]))
        self.assertContains(page, "Carol Test")
        self.assertNotContains(page, 'name="person"')
