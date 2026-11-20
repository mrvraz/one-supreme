"""Who can reach what: every address in the hub, for every kind of person, checked against one table.

The table is docs/security/ACCESS-MATRIX.md. The addresses come from Django's URL resolver, so a page added
anywhere fails here until someone writes down who may open it. Every row must match what the page really does,
for GET and for POST, with the real records, with records that don't exist, and in the admin. To change who may
do what, change the table first, then the code.
"""

import logging
import re
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.test.client import RedirectCycleError
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone
from PIL import Image

from chat.models import Conversation, Membership, Message
from jobs.models import Vacancy
from journeys.models import Journey, Step, assign
from library.models import Article, Category, Document, FeaturedLink, Folder

from . import plugins
from .models import (
    RSVP, Attachment, Comment, Community, Event, FeatureNote, GroupInvite, Notification, PollOption, PollVote, Post,
    Report, User,
)
from .security import record_change

TABLE = Path(settings.BASE_DIR) / "docs" / "security" / "ACCESS-MATRIX.md"

# Column in the table -> the test user who plays that part (made in setUpTestData). None is nobody signed in.
SIGNED_IN = {
    "Colleague": "colleague", "Member": "member", "Author": "author", "Publisher": "publisher", "Editor": "editor",
    "Org admin": "orgadmin", "Moderator": "moderator", "Superuser": "superuser",
}
OUTSIDE = {"Signed out": None, "Leaver": "leaver", "New starter": "starter"}
OUTSIDE_USUALLY = {"Signed out": "sign in", "Leaver": "sign in", "New starter": "rules"}  # when the table says nothing
NO_STAFF = ["colleague", "member", "author", "editor"]  # the admin's "No staff status"
# The admin sections table: (name in brackets) -> test user. The first two need a row for every section; the others
# are refused wherever they have none.
ADMIN_STAFF = {"moderator": "moderator", "superuser": "superuser", "publisher": "publisher", "org admin": "orgadmin"}
ADMIN_KINDS = {"changelist": "List", "add": "Add", "change": "Open", "history": "History", "delete": "Delete"}
COLUMNS = {*SIGNED_IN, *OUTSIDE, "No staff status", *ADMIN_KINDS.values()}

# Which record each address is about, by how the address starts (first match wins).
RECORDS = [
    ("posts/", lambda f: {"pk": f.poll.pk}),
    ("comments/", lambda f: {"pk": f.comment.pk}),
    ("news/", lambda f: {"pk": f.news.pk}),
    ("people/", lambda f: {"pk": f.author.pk}),
    ("groups/", lambda f: {"slug": f.group.slug, "user_id": f.member.pk}),
    ("invites/", lambda f: {"pk": f.request.pk}),
    ("events/", lambda f: {"pk": f.event.pk}),
    ("notifications/", lambda f: {"pk": f.notification.pk}),
    ("chat/with/", lambda f: {"user_id": f.author.pk}),
    ("chat/messages/", lambda f: {"pk": f.message.pk}),
    ("chat/", lambda f: {"pk": f.chat.pk}),
    ("library/files/folders/", lambda f: {"pk": f.folder.pk}),
    ("library/files/", lambda f: {"pk": f.document.pk}),
    ("library/featured/links/", lambda f: {"pk": f.link.pk}),
    ("library/groups/", lambda f: {"slug": f.group.slug}),
    ("library/kb/", lambda f: {"pk": f.article.pk}),
    ("journeys/", lambda f: {"pk": f.journey.pk, "step_pk": f.step.pk}),
    ("jobs/", lambda f: {"pk": f.vacancy.pk}),
    ("admin/r/", lambda f: {"content_type_id": ContentType.objects.get_for_model(Post).pk, "object_id": f.poll.pk}),
]
# Addresses with one row per thing they point at: (url name, the bracket after it in the table) -> arguments.
CASES = {
    ("report", "post"): lambda f: {"kind": "post", "pk": f.poll.pk},
    ("report", "comment"): lambda f: {"kind": "comment", "pk": f.comment.pk},
    ("report", "person"): lambda f: {"kind": "person", "pk": f.author.pk},
    ("translate", "post"): lambda f: {"kind": "post", "pk": f.poll.pk},
    ("translate", "comment"): lambda f: {"kind": "comment", "pk": f.comment.pk},
    # One row per upload folder (plugins.MEDIA_GUARDS), with a file from the private group where it can be one.
    ("media", "posts"): lambda f: {"path": f.attachment.file.name},
    ("media", "comments"): lambda f: {"path": f.comment.image.name},
    ("media", "covers"): lambda f: {"path": f.news.cover.name},
    ("media", "avatars"): lambda f: {"path": f.author.avatar.name},
    ("media", "chat"): lambda f: {"path": f.message.image.name},
    ("media", "library"): lambda f: {"path": f.document.file.name},
    ("media", "journeys"): lambda f: {"path": f.draft_journey.cover.name},
    ("admin:app_list", "hub"): lambda f: {"app_label": "hub"},
    ("admin:app_list", "admin"): lambda f: {"app_label": "admin"},
    ("admin:app_list", "auth"): lambda f: {"app_label": "auth"},
    ("admin:app_list", "library"): lambda f: {"app_label": "library"},
}
MISSING = {"pk": 999999, "user_id": 999999, "step_pk": 999999, "slug": "no-such-group"}


def routes(patterns=None, prefix="", namespace=""):
    """(url name, route) for every address Django knows, e.g. ("chat:thread", "chat/<int:pk>/")."""
    for pattern in get_resolver().url_patterns if patterns is None else patterns:
        if isinstance(pattern, URLResolver):
            inner = f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            yield from routes(pattern.url_patterns, prefix + str(pattern.pattern), inner)
        else:
            yield f"{namespace}{pattern.name}", prefix + str(pattern.pattern)


def admin_section(route):
    """("hub.post", "change") for an admin page about one model, or None for the admin's other pages."""
    found = re.fullmatch(r"admin/(\w+)/(\w+)/(<[^>]+>/)?(\w+/)?", route)
    labels = {model._meta.label_lower for model in admin.site._registry}
    if not found or f"{found[1]}.{found[2]}" not in labels:
        return None
    kind = (found[4] or "").strip("/") or ("redirect" if found[3] else "changelist")  # redirect: on to "change"
    return f"{found[1]}.{found[2]}", {"password": "change"}.get(kind, kind)


def addresses():
    """(the name the table uses, route) for every address except the admin's pages about one model."""
    for name, route in routes():
        if "(?P<url>" in route:
            yield "admin:catch_all", "admin/no-such-page/"  # the admin's "any other address", which has no name
        elif not admin_section(route):
            yield name, route


def read_table():
    """{(url name, case or ""): {method: {column: cell}}} from every table in the document."""
    rows, header = {}, None
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            header = None  # the next table starts with its own header
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if "Address" not in header or set(cells[0]) <= {"-", ":"}:
            continue  # a table of something else, or the line under a header
        row = dict(zip(header, cells))
        found = re.fullmatch(r"`([^`]+)`(?: \((.+)\))?", row["Address"])
        assert found, f"{TABLE.name}: can't read the address in {line}"
        key = (found[1], found[2] or "")
        for method in row.get("Method", "GET, POST").split(", "):
            given = rows.setdefault(key, {}).setdefault(method, {})
            for column, cell in row.items():
                if column in COLUMNS:
                    assert column not in given, f"{TABLE.name}: {key} {method} {column} is given twice"
                    given[column] = cell
    return rows


def outcome(response):
    """The word the table uses for this answer."""
    status = response.status_code
    if status in (301, 302, 303, 307, 308):
        where = response["Location"]
        if where.startswith(reverse("login")):
            return "sign in"
        return "rules" if where.startswith(reverse("house_rules")) else "yes"
    if getattr(response, "redirect_chain", None):  # an admin page, followed to where it ends
        if response.request["PATH_INFO"] == reverse("login"):
            return "sign in"
        if response.request["PATH_INFO"] == reverse("house_rules"):
            return "rules"
    words = {403: "refused", 404: "hidden", 405: "wrong method", 400: "bad request", 429: "too many"}
    return words.get(status, "yes" if status < 300 else f"error {status}")


def picture(name):
    out = BytesIO()
    Image.new("RGB", (4, 4), "white").save(out, "PNG")
    return ContentFile(out.getvalue(), name=name)


def allow(user, *codenames):
    for codename in codenames:
        app, code = codename.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=code))


@override_settings(
    TRANSLATE_URL="http://translate.invalid", OIDC_RP_CLIENT_ID="matrix",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://sign-in.invalid/authorize", OIDC_OP_TOKEN_ENDPOINT="https://sign-in.invalid/token",
    OIDC_OP_USER_ENDPOINT="https://sign-in.invalid/userinfo", LOGIN_REDIRECT_URL_FAILURE="/login/?error=sso",
)
class AccessMatrix(TestCase):
    """The cast, the records they own, one signed-in browser each, and the checks the tests below share."""

    @classmethod
    def setUpClass(cls):
        # A folder per class: CI's parallel workers run the classes side by side, and each deletes its own at the end.
        media = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, media, ignore_errors=True)
        cls.enterClassContext(override_settings(MEDIA_ROOT=media))
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        def person(name, **extra):
            extra.setdefault("policy_version", settings.POLICY_VERSION)
            return User.objects.create_user(name, f"{name}@example.com", first_name=name.title(), last_name="Test", **extra)

        f = cls.f = SimpleNamespace()
        for name in ("colleague", "member", "author", "editor"):
            setattr(f, name, person(name))
        # Communications and org admins also work in the admin (units, What's new), so they get staff status as at Supreme.
        f.publisher, f.orgadmin = person("publisher", is_staff=True), person("orgadmin", is_staff=True)
        f.starter = person("starter", policy_version="")
        f.leaver = person("leaver", is_active=False)
        f.moderator = person("moderator", is_staff=True)
        f.superuser = person("superuser", is_staff=True, is_superuser=True)
        # The roles, set up as README.md ("Roles") tells Supreme's IT to.
        allow(f.publisher, "hub.publish_news", "hub.view_insights")
        allow(f.editor, *(
            f"{app}.{action}_{model}" for action in ("add", "change", "delete")
            for app, model in [("library", "document"), ("library", "folder"), ("library", "featuredlink"),
                               ("library", "article"), ("library", "category"), ("journeys", "journey"), ("jobs", "vacancy")]
        ))
        allow(f.orgadmin, "hub.change_community")
        moderators = Group.objects.create(name="Moderators")
        moderators.permissions.set(Permission.objects.filter(
            content_type__app_label__in=["hub", "admin"],
            codename__regex=r"^(view|change|delete)_(post|comment|report)$|^view_logentry$",
        ))
        f.moderator.groups.add(moderators)
        f.author.avatar.save("author.png", picture("author.png"))

        # The private group: the author started it (so is its admin) and the member is in it. Nobody else is.
        now = timezone.now()
        f.group = Community.objects.create(name="Private project", slug="private-project", is_private=True, created_by=f.author)
        f.group.members.add(f.author, f.member)
        f.group.admins.add(f.author)
        f.request = GroupInvite.objects.create(community=f.group, user=f.colleague, kind=GroupInvite.REQUEST, created_by=f.colleague)
        f.poll = Post.objects.create(kind=Post.POLL, author=f.author, community=f.group, body="Lunch?", notified_at=now)
        f.option = PollOption.objects.create(post=f.poll, text="Yes")
        f.attachment = Attachment.objects.create(post=f.poll, file=picture("photo.png"), kind=Attachment.IMAGE)
        f.comment = Comment.objects.create(post=f.poll, author=f.author, body="Me too", image=picture("comment.png"))
        f.news = Post.objects.create(
            kind=Post.NEWS, author=f.publisher, title="Pay day", body="Read me", requires_ack=True, notified_at=now,
            cover=picture("cover.png"),
        )
        f.news.audiences.add(f.group)  # the publisher sends it to the private group without being in it
        f.event = Event.objects.create(title="Away day", starts_at=now + timedelta(days=2), community=f.group, created_by=f.author)
        for who in (f.author, f.member):
            RSVP.objects.create(event=f.event, user=who, status=RSVP.Status.GOING)
        f.notification = Notification.objects.create(recipient=f.author, message="For the author", url="/")
        Report.objects.create(reporter=f.member, post=f.poll, reason="Off topic")

        f.chat = Conversation.objects.create(is_group=True, name="Project chat", created_by=f.author)
        for who in (f.author, f.member):
            Membership.objects.create(conversation=f.chat, user=who, joined_at=now - timedelta(hours=1))
        f.message = Message.objects.create(conversation=f.chat, sender=f.author, body="Hello", image=picture("chat.png"))

        f.folder = Folder.objects.create(name="Plans", community=f.group, created_by=f.author)
        f.document = Document.objects.create(
            folder=f.folder, community=f.group, title="Plan", file=ContentFile(b"%PDF-1.4\n", name="plan.pdf"),
            original_name="plan.pdf", size=9, uploaded_by=f.author,
        )
        f.link = FeaturedLink.objects.create(title="Board", url="https://example.com/", community=f.group, created_by=f.author)
        f.article = Article.objects.create(category=Category.objects.create(name="How to"), title="Parking", body="Text")

        f.journey = Journey.objects.create(title="Project start", is_published=True, created_by=f.editor)
        f.journey.audiences.add(f.group)
        f.step = Step.objects.create(journey=f.journey, title="Meet the team")
        assign(f.journey, f.journey.audience())  # the author and the member
        f.draft_journey = Journey.objects.create(title="Draft", cover=picture("journey.png"), created_by=f.editor)
        f.vacancy = Vacancy.objects.create(
            title="Driver", location="Warehouse", department="Transport", description="Drive", contact=f.author, created_by=f.editor
        )
        FeatureNote.objects.create(title="New", body="Things")
        record_change(f.superuser, f.poll, "Checked")  # a line in the audit log, for its admin pages

    def setUp(self):
        logging.disable(logging.CRITICAL)  # thousands of expected refusals would each log a warning
        self.addCleanup(logging.disable, logging.NOTSET)
        self.table = read_table()
        self.clients = {None: Client(raise_request_exception=False)}
        for name in [*SIGNED_IN.values(), "leaver", "starter"]:
            self.clients[name] = Client(raise_request_exception=False)
            self.clients[name].force_login(getattr(self.f, name))
        translated = mock.Mock(status_code=200, json=lambda: {"translatedText": "Hola"})
        for patcher in (
            mock.patch("hub.views.requests.post", return_value=translated),  # no translation server in tests
            mock.patch("django.core.files.storage.FileSystemStorage.delete"),  # undoing a request can't bring a file back
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def payload(self, name):
        """What the forms send: enough for most actions to go ahead. "yes" only means the access check let the request
        through; what each action then does is checked in tests_features and the other test modules."""
        f = self.f
        if name.startswith("push_"):
            return {"endpoint": "https://fcm.googleapis.com/fcm/send/matrix", "keys": {"p256dh": "key", "auth": "secret"}}
        return {
            "body": "Checked by the access matrix", "kind": "like", "option": f.option.pk, "reason": "Access matrix",
            "status": "going", "answer": "accept", "action": "admin", "user": f.colleague.pk, "add": f.colleague.pk,
            "look": "daylight", "title": "Access matrix", "name": "Access matrix", "note": "Interested", "featured": "1",
            "publish": "1", "open": "1", "url": "https://example.com/", "draft": "1",
        }

    def ask(self, who, method, url, name="", follow=False):
        """One request, undone afterwards, so every request meets the same records. Returns the table's word."""
        client = self.clients[who]
        data = self.payload(name) if method == "POST" else {}
        extra = {"content_type": "application/json"} if method == "POST" and name.startswith("push_") else {}
        with transaction.atomic():
            try:
                answer = outcome(getattr(client, method.lower())(url, data, follow=follow, **extra))
            except RedirectCycleError:
                answer = "loop"
            transaction.set_rollback(True)
        if who and not client.cookies.get(settings.SESSION_COOKIE_NAME, SimpleNamespace(value="")).value:
            client.force_login(getattr(self.f, who))  # that request signed them out
        return answer

    def fill(self, name, route, case, missing=False):
        """The address with its <arguments> filled in: the real records, or ones that don't exist."""
        wanted = [a or b for a, b in re.findall(r"<(?:\w+:)?(\w+)>|\(\?P<(\w+)>", route)]
        if not wanted:
            return None if missing else "/" + route
        if (name, case) in CASES:
            given = CASES[name, case](self.f)
        else:
            given = next((make(self.f) for start, make in RECORDS if route.startswith(start)), None)
            self.assertIsNotNone(given, f"No record for {route}: add one to RECORDS in {__name__}")
        given = {key: value for key, value in given.items() if key in wanted}
        if missing:
            given = {key: MISSING.get(key, value) for key, value in given.items()}
            if "path" in given:
                given["path"] = given["path"].rsplit("/", 1)[0] + "/no-such-file.png"
        return reverse(name, kwargs=given)

    def cell(self, key, method, column):
        rows = self.table.get(key, {})
        if column in rows.get(method, {}):
            return rows[method][column]
        if column in OUTSIDE_USUALLY:
            return OUTSIDE_USUALLY[column]
        if method == "GET" and column in rows.get("POST", {}):
            return "wrong method"  # a button: following a plain link to it gets "Method not allowed"
        return None

    def keys(self, name):
        return [(n, case) for n, case in sorted(CASES) if n == name] or [(name, "")]

    def check(self, items, columns, follow=False):
        """Ask every address as every column's person, and list each answer that isn't the table's."""
        wrong = []
        for name, route in items:
            for key in self.keys(name):
                url = self.fill(name, route, key[1])
                for method in ("GET", "POST"):
                    for column, who in columns.items():
                        expected, got = self.cell(key, method, column), self.ask(who, method, url, name, follow)
                        if got != expected:
                            wrong.append(f"{key} {method} {column}: table says {expected!r}, page gives {got!r}")
        if wrong:
            self.fail(f"{len(wrong)} answers differ from {TABLE.name}:\n" + "\n".join(wrong))

    def site(self, namespaced):
        """The hub's own addresses (namespaced=False), or those of chat, library, journeys and jobs."""
        return [(n, r) for n, r in addresses() if not r.startswith("admin/") and (":" in n) == namespaced]


class PagesForEveryone(AccessMatrix):
    def test_every_address_has_a_row_and_every_row_an_address(self):
        sections = {model._meta.label_lower for model in admin.site._registry}
        for name, route in addresses():
            for key in self.keys(name):
                self.assertTrue(key in self.table, f"{route} {key} has no row in {TABLE.name}: decide who may open it")
        for label in sections:
            for who in ("moderator", "superuser"):
                self.assertTrue((label, who) in self.table, f"The admin section {label} has no row for the {who}")
        cases = {case for name, case in self.table if name in sections}
        self.assertEqual(cases - set(ADMIN_STAFF), set(), "Admin section rows for someone the test doesn't play")
        known = {name for name, _route in addresses()} | sections
        self.assertEqual({name for name, _case in self.table} - known, set(), f"Rows in {TABLE.name} for addresses that are gone")
        self.assertEqual({case for name, case in CASES if name == "media"}, set(plugins.MEDIA_GUARDS), "One media row per folder")

    def test_hub_pages(self):
        self.check(self.site(namespaced=False), SIGNED_IN)

    def test_chat_library_journeys_and_jobs(self):
        self.check(self.site(namespaced=True), SIGNED_IN)

    def test_signed_out_leavers_and_new_starters(self):
        self.check(self.site(namespaced=False) + self.site(namespaced=True), OUTSIDE)

    def test_records_that_do_not_exist(self):
        """A made-up ID never gives more than the real one, and the people who may act are told "not found"."""
        wrong = []
        for name, route in self.site(namespaced=False) + self.site(namespaced=True):
            for key in self.keys(name):
                url = self.fill(name, route, key[1], missing=True)
                if url is None:
                    continue
                for method in ("GET", "POST"):
                    for column, who in SIGNED_IN.items():
                        real = self.cell(key, method, column)
                        allowed = {"yes": {"hidden"}, "hidden": {"hidden"}, "refused": {"refused", "hidden"}}.get(real, {real})
                        got = self.ask(who, method, url, name)
                        if got not in allowed:
                            wrong.append(f"{url} {method} {column}: expected {' or '.join(sorted(allowed))}, page gives {got!r}")
        if wrong:
            self.fail(f"{len(wrong)} answers differ from {TABLE.name}:\n" + "\n".join(wrong))

    def test_only_staff_status_sends_an_announcement(self):
        """The feed's Announcement tick pins a post and tells everyone. It comes with staff status and nothing else."""
        for who, kept in [("colleague", False), ("editor", False), ("publisher", True), ("orgadmin", True)]:
            response = self.clients[who].post(reverse("feed"), {"body": f"From the {who}", "is_announcement": "on"})
            self.assertEqual(response.status_code, 302, who)
            self.assertEqual(Post.objects.get(body=f"From the {who}").is_announcement, kept, who)

    def test_a_private_groups_page_lists_its_posts_only_for_those_who_may_open_them(self):
        page = reverse("community", args=[self.f.group.slug])
        self.assertContains(self.clients["member"].get(page), "Lunch?")
        self.assertNotContains(self.clients["orgadmin"].get(page), "Lunch?")  # runs the group, but isn't in it

    def test_ids_that_belong_to_something_else(self):
        """Two real IDs that don't go together: a step of another journey, someone who isn't in the group."""
        f = self.f
        other_step = Step.objects.create(journey=Journey.objects.create(title="Other", is_published=True), title="Elsewhere")
        other_poll = Post.objects.create(kind=Post.POLL, author=f.author, body="Tea?", notified_at=timezone.now())
        other_option = PollOption.objects.create(post=other_poll, text="Yes")
        for who, method, url, data, expected in [
            ("editor", "get", reverse("journeys:step", args=[f.journey.pk, other_step.pk]), {}, 404),
            ("editor", "get", reverse("journeys:step_edit", args=[f.journey.pk, other_step.pk]), {}, 404),
            ("editor", "post", reverse("journeys:step_delete", args=[f.journey.pk, other_step.pk]), {}, 404),
            ("member", "post", reverse("journeys:step_done", args=[f.journey.pk, other_step.pk]), {}, 404),
            ("author", "post", reverse("community_member_change", args=[f.group.slug, f.colleague.pk]), {"action": "admin"}, 404),
            ("member", "post", reverse("poll_vote", args=[f.poll.pk]), {"option": other_option.pk}, 400),
        ]:
            self.assertEqual(getattr(self.clients[who], method)(url, data).status_code, expected, url)
        self.assertTrue(Step.objects.filter(pk=other_step.pk).exists())
        self.assertFalse(f.group.admins.filter(pk=f.colleague.pk).exists())
        self.assertFalse(PollVote.objects.exists())


class AdminPages(AccessMatrix):
    """The admin is Django's own. This checks who gets in at all, and how far a moderator reaches inside."""

    def test_admin_pages_that_are_not_about_one_model(self):
        pages = [(name, route) for name, route in addresses() if route.startswith("admin/")]
        staff = {"Publisher": "publisher", "Org admin": "orgadmin", "Moderator": "moderator", "Superuser": "superuser"}
        self.check(pages, {**OUTSIDE, **staff}, follow=True)
        for who in NO_STAFF:
            self.check(pages, {"No staff status": who}, follow=True)

    def test_every_admin_section(self):
        """Per model, what each person with staff status can open. Nobody else gets in at all."""
        wrong = []
        models = {model._meta.label_lower: model for model in admin.site._registry}
        for _name, route in routes():
            if not admin_section(route):
                continue
            label, kind = admin_section(route)
            obj = models[label].objects.order_by("pk").first()
            self.assertIsNotNone(obj, f"Make a {label} in setUpTestData, so its admin pages can be opened")
            url = "/" + re.sub(r"<[^>]+>", str(obj.pk), route)
            column = ADMIN_KINDS["change" if kind == "redirect" else kind]
            for method in ("GET", "POST"):
                # "view only": the page opens, but saving or deleting is refused. The bare address only redirects.
                saving = method == "POST" and kind != "redirect"
                cells = {who: self.cell((label, case), "GET", column) or "refused" for case, who in ADMIN_STAFF.items()}
                cells = {who: {"view only": "refused" if saving else "yes"}.get(cell, cell) for who, cell in cells.items()}
                for who, want in [*cells.items(), ("colleague", "refused"), ("starter", "rules"), (None, "sign in")]:
                    got = self.ask(who, method, url, follow=True)
                    if got != want:
                        wrong.append(f"{url} {method} {who}: expected {want!r}, page gives {got!r}")
        if wrong:
            self.fail(f"{len(wrong)} answers differ from {TABLE.name}:\n" + "\n".join(wrong))

    def test_a_moderator_cannot_change_who_wrote_something_or_where_it_went(self):
        """Saving works (they may hide it), but the author, the group, the words and the date stay as they were."""
        f = self.f
        # A whole form, so that without the rule it would save the new author: the test then fails on what changed.
        moved = {"author": f.superuser.pk, "community": "", "post": f.news.pk, "body": "Changed", "kind": Post.UPDATE,
                 "created_at_0": "2020-01-01", "created_at_1": "09:00:00", "is_hidden": "on"}
        post_only = {"attachments-TOTAL_FORMS": 1, "attachments-INITIAL_FORMS": 1, "attachments-0-id": f.attachment.pk,
                     "attachments-0-post": f.poll.pk, "last_activity_at_0": "2026-11-20", "last_activity_at_1": "09:00:00"}
        for item, extra in [(f.poll, post_only), (f.comment, {})]:
            url = reverse(f"admin:hub_{item._meta.model_name}_change", args=[item.pk])
            theirs = ("is_hidden", "last_activity_at")  # what a moderator may change here
            fields = [field.attname for field in item._meta.concrete_fields if field.name not in theirs]
            rows = type(item).objects.filter(pk=item.pk)
            before = rows.values(*fields).get()
            self.assertEqual(self.clients["moderator"].post(url, {**moved, **extra}).status_code, 302, url)
            self.assertTrue(rows.get().is_hidden, url)
            self.assertEqual(rows.values(*fields).get(), before, url)
