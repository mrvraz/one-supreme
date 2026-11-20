"""Query ceilings for the pages the load test found slow: their queries must not grow with posts, comments,
reactions or rows, and each page loads only what it shows. (The red team checks a few pages of its own.)"""

from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from chat.models import Conversation, Message
from .models import Comment, Community, Event, Post, PostRead, Reaction, Report, User
from .views import PAGE_THREADS


def make_user(name, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)
    return User.objects.create_user(name, f"{name}@example.com", None, first_name=name.title(), last_name="Test", **extra)


class QueryCeilingTests(TestCase):
    def setUp(self):
        self.me, self.mod = make_user("me"), make_user("mod", is_staff=True, is_superuser=True)
        self.others = [make_user(f"colleague{n}") for n in range(6)]
        self.team = Community.objects.create(name="Ops team", slug="ops", kind=Community.UNIT, unit_type="team")
        self.site = Community.objects.create(name="Warehouse", slug="warehouse", kind=Community.UNIT, unit_type="location")
        self.club = Community.objects.create(name="Running club", slug="running")
        for place in (self.team, self.site, self.club):
            place.members.add(self.me, *self.others)
        self.client.force_login(self.me)

    def add(self, n):
        """n more of everything the busy pages show, each with comments, replies and reactions."""
        author = self.others[0]
        for i in range(n):
            posts = [
                Post.objects.create(author=author, body=f"For everyone {i}", pinned_at=timezone.now() if i == 0 else None),
                Post.objects.create(author=author, body=f"For the club {i}", community=self.club, pinned_at=timezone.now() if i == 0 else None),
                Post.objects.create(author=author, body=f"For the team {i}", community=self.team),
                Post.objects.create(author=author, kind=Post.POLL, body=f"Lunch? {i}"),
                Post.objects.create(author=author, kind=Post.NEWS, title=f"News {i}", body="Read me", requires_ack=True),
            ]
            posts[-1].audiences.set([self.team, self.site])
            posts[-2].options.create(text="Yes")
            event = Event.objects.create(title=f"Social {i}", starts_at=timezone.now() + timedelta(days=3), created_by=author)
            posts.append(Post.objects.create(author=author, kind=Post.EVENT, event=event))
            for post in posts:
                for person in self.others:
                    thread = Comment.objects.create(post=post, author=person, body="Nice")
                    Comment.objects.create(post=post, author=self.me, parent=thread, body="Thanks")
                    thread.reactions.create(user=self.me, kind="like")
                    post.reactions.create(user=person, kind="love" if person.pk % 2 else "like")
                PostRead.objects.create(post=post, user=self.mod)
            Report.objects.create(reporter=self.me, comment=thread, reason="Rude")
            chat = Conversation.objects.create(is_group=True, name=f"Chat {Conversation.objects.count()}")
            chat.memberships.create(user=self.me)
            Message.objects.create(conversation=chat, sender=self.me, body="Hi")

    def queries(self, url, user=None):
        self.client.force_login(user or self.me)
        self.client.get(url)  # once first, so the once-a-minute "last seen" update doesn't count
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        return len(ctx)

    def test_busy_pages_run_the_same_queries_for_2_or_6_of_everything(self):
        pages = {
            "feed": (reverse("feed"), None), "feed by activity": (reverse("feed") + "?sort=activity", None),
            "group": (self.club.get_absolute_url(), None), "profile": (self.others[0].get_absolute_url(), None),
            "news": (reverse("news"), None), "unread news": (reverse("news") + "?show=unread", None),
            "chat list": (reverse("chat:list"), None),
            "moderator's feed": (reverse("feed"), self.mod), "admin posts": (reverse("admin:hub_post_changelist"), self.mod),
            "admin reports": (reverse("admin:hub_report_changelist"), self.mod),
            "admin events": (reverse("admin:hub_event_changelist"), self.mod),
        }
        # With some room. A page that needs more than this is doing something new and should be looked at.
        ceilings = {
            "feed": 44, "feed by activity": 44, "group": 50, "profile": 31, "news": 14, "unread news": 14, "chat list": 12,
            "moderator's feed": 42, "admin posts": 12, "admin reports": 11, "admin events": 12,
        }
        self.add(2)
        few = {name: self.queries(url, user) for name, (url, user) in pages.items()}
        self.add(4)
        many = {name: self.queries(url, user) for name, (url, user) in pages.items()}
        for name in pages:
            self.assertLessEqual(many[name], few[name], name)
            self.assertLessEqual(many[name], ceilings[name], name)

    def test_the_busiest_post_runs_the_same_queries_with_12_or_96_comments(self):
        post = Post.objects.create(author=self.others[0], body="Welcome to the hub")
        counts = []
        for rounds in (1, 7):
            for person in self.others * rounds:
                thread = Comment.objects.create(post=post, author=person, body="Hello")
                Comment.objects.create(post=post, author=self.me, parent=thread, body="Hi back")
                thread.reactions.create(user=person, kind="like")
            counts.append(self.queries(post.get_absolute_url()))
        self.assertLessEqual(counts[1], counts[0])
        self.assertLessEqual(counts[1], 26)

    def test_cards_load_the_newest_threads_and_the_post_page_the_newest_fifty(self):
        post = Post.objects.create(author=self.others[0], body="Big news")
        start = timezone.now() - timedelta(hours=2)
        Comment.objects.bulk_create(
            Comment(post=post, author=self.others[n % 6], body=f"Comment {n}", created_at=start + timedelta(minutes=n))
            for n in range(PAGE_THREADS + 5)
        )
        newest = Comment.objects.get(body=f"Comment {PAGE_THREADS + 4}")
        Comment.objects.create(post=post, author=self.me, parent=newest, body="A reply")
        newest.reactions.create(user=self.me, kind="like")
        post.reactions.create(user=self.me, kind="like")
        post.reactions.create(user=self.others[0], kind="like")
        post.reactions.create(user=self.others[1], kind="love")

        response = self.client.get(reverse("feed"))
        card = next(p for p in response.context["posts"] if p.pk == post.pk)
        self.assertEqual([c.body for c in card.comment_list], [f"Comment {n}" for n in range(PAGE_THREADS + 2, PAGE_THREADS + 5)])
        self.assertEqual([r.body for r in card.comment_list[-1].reply_list], ["A reply"])
        self.assertEqual((card.comment_list[-1].my_reaction, card.comment_list[-1].reaction_total), ("like", 1))
        self.assertEqual((card.comment_total, card.reaction_total, card.reaction_emojis, card.my_reaction), (56, 3, "👍❤️", "like"))
        self.assertContains(response, "View all 56 comments")

        page = self.client.get(post.get_absolute_url())
        shown = page.context["post"].comment_list
        self.assertEqual((len(shown), shown[0].body, shown[-1].body), (PAGE_THREADS, "Comment 5", f"Comment {PAGE_THREADS + 4}"))
        self.assertContains(page, 'href="?comments=all#comments"')
        everything = self.client.get(post.get_absolute_url() + "?comments=all")
        self.assertEqual(len(everything.context["post"].comment_list), PAGE_THREADS + 5)
        self.assertNotContains(everything, 'href="?comments=all#comments"')

        # After a reaction the card comes back with the threads its page was showing.
        def refreshed(page_url, full):
            data = {"kind": "wow", **({"full": "1"} if full else {})}
            response = self.client.post(reverse("react", args=[post.pk]), data, HTTP_X_FRAGMENT="1", HTTP_REFERER=page_url)
            return len(response.context["post"].comment_list)

        self.assertEqual(refreshed("http://testserver/", full=False), 3)
        self.assertEqual(refreshed(f"http://testserver{post.get_absolute_url()}", full=True), PAGE_THREADS)
        self.assertEqual(refreshed(f"http://testserver{post.get_absolute_url()}?comments=all", full=True), PAGE_THREADS + 5)

    def test_news_for_two_of_my_teams_shows_once_and_counts_once(self):
        news = Post.objects.create(author=self.others[0], kind=Post.NEWS, title="For two teams", body="Hello")
        news.audiences.set([self.team, self.site])
        for person in self.others[:3]:
            news.reactions.create(user=person, kind="like")
            Comment.objects.create(post=news, author=person, body="Thanks")
        Comment.objects.create(post=news, author=self.others[4], body="Hidden", is_hidden=True)

        feed = self.client.get(reverse("feed"))
        self.assertEqual([p.pk for p in feed.context["posts"]], [news.pk])
        self.assertEqual((feed.context["page"].paginator.count, feed.context["unread_news"]), (1, 1))
        self.assertEqual([p.pk for p in self.client.get(reverse("feed") + "?scope=mine").context["posts"]], [news.pk])
        self.assertEqual(list(self.client.get(reverse("feed") + "?scope=company").context["posts"]), [])
        listed = self.client.get(reverse("news")).context["page"].object_list
        self.assertEqual([(p.pk, p.reaction_count, p.comment_count) for p in listed], [(news.pk, 3, 3)])
        # Someone in neither team doesn't see it.
        outsider = make_user("outsider")
        self.client.force_login(outsider)
        self.assertEqual(list(self.client.get(reverse("feed")).context["posts"]), [])


class LoadToolTests(TestCase):
    def test_seed_load_fills_an_empty_database_and_the_benchmark_opens_every_page(self):
        call_command("seed_load", scale=0.01, force=True, stdout=StringIO())
        self.assertEqual(User.objects.count(), 20)
        self.assertTrue(Reaction.objects.exists() and Message.objects.exists() and Comment.objects.filter(parent__isnull=False).exists())
        out = StringIO()
        call_command("benchmark", runs=1, stdout=out)
        table = out.getvalue()
        self.assertIn("| Feed |", table)
        self.assertIn("| Admin: reports |", table)
        self.assertNotIn("HTTP", table)  # every page answered 200
        with self.assertRaisesMessage(Exception, "only fills an empty one"):
            call_command("seed_load", scale=0.01, force=True, stdout=StringIO())
