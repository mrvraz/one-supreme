"""Times the 15 pages staff open most, for an ordinary colleague and for a moderator, and counts their queries.

Run it on a database filled by seed_load:  python manage.py benchmark
It opens pages like a person would (opening a chat marks it read), so use a test copy of the hub.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Count
from django.test import Client, override_settings
from django.urls import reverse

from chat.models import Membership, Message
from hub.models import Comment, Community, Post, User


def pages(user):
    """(name, address) of the busiest pages, using the biggest post, group and chat this person can open."""
    post = Post.objects.visible().filter(kind=Post.UPDATE, community=None).annotate(n=Count("comments")).order_by("-n")[0]
    group = user.communities.filter(kind=Community.GROUP).annotate(n=Count("posts")).order_by("-n")[0]
    chat = Membership.objects.filter(user=user).annotate(n=Count("conversation__messages")).order_by("-n")[0].conversation
    newest = Message.objects.filter(conversation=chat).order_by("-pk").values_list("pk", flat=True).first() or 0
    poster = User.objects.annotate(n=Count("posts")).order_by("-n")[0]
    return [
        ("Feed", reverse("feed")),
        ("Feed, recent activity", reverse("feed") + "?sort=activity"),
        ("Post with the most comments", post.get_absolute_url()),
        ("News", reverse("news")),
        ("Notifications", reverse("notifications")),
        ("Chat list", reverse("chat:list")),
        ("Busiest chat", chat.get_absolute_url()),
        ("Chat: check for new messages", reverse("chat:poll", args=[chat.pk]) + f"?after={newest}"),
        ("Groups", reverse("communities") + "?show=all"),
        ("Busiest group", group.get_absolute_url()),
        ("People", reverse("people")),
        ("Profile of the busiest poster", poster.get_absolute_url()),
        ("Events", reverse("events")),
        ("Search", reverse("search") + "?q=team"),
        ("Recent files", reverse("library:files") + "?tab=recent"),
    ]


# Pages only moderators and admins open.
ADMIN_PAGES = [("Insights", "insights"), ("Admin: posts", "admin:hub_post_changelist"), ("Admin: reports", "admin:hub_report_changelist")]


def timed(log, execute, sql, params, many, context):
    """Note how long each query takes (Django's own query timer only ticks every 15 ms on Windows)."""
    started = time.perf_counter()
    try:
        return execute(sql, params, many, context)
    finally:
        log.append(((time.perf_counter() - started) * 1000, sql))


class Command(BaseCommand):
    help = "Time the busiest pages and count their database queries (on a database filled by seed_load)."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=7, help="Times each page is opened; the fastest is shown.")
        parser.add_argument("--sql", action="store_true", help="Also show the slowest query of each page.")

    def handle(self, *args, runs, sql, **options):
        people = {user.username: user for user in User.objects.filter(username__in=["load-user", "load-admin"])}
        if len(people) < 2:
            raise CommandError("Fill the database with seed_load first.")
        roles = {"load-user": "Colleague", "load-admin": "Moderator"}
        results = {}
        # The test client's address is "testserver", and https so the HTTPS redirect doesn't answer instead.
        with override_settings(ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, "testserver"]):
            for username in roles:
                user, client = people[username], self.client_for(people[username])
                todo = pages(user) + ([(name, reverse(url)) for name, url in ADMIN_PAGES] if user.is_superuser else [])
                results[username] = {name: self.measure(client, url, runs) for name, url in todo}

        self.stdout.write(
            f"Fastest of {runs} runs on {connection.vendor}: {User.objects.count()} people, {Post.objects.count()} posts, "
            f"{Comment.objects.count()} comments. Times in milliseconds; SQL is the part spent in the database.\n"
        )
        self.stdout.write("| Page | " + " | ".join(f"{r} | SQL | Queries" for r in roles.values()) + " |")
        self.stdout.write("|---|" + "--:|" * 3 * len(roles))
        for name in results["load-admin"]:
            cells = [results[username].get(name) for username in roles]
            self.stdout.write(f"| {name} | " + " | ".join(" | ".join(map(str, c[:3])) if c else "- | - | -" for c in cells) + " |")
        if sql:
            for username, rows in results.items():
                for name, (_ms, sql_ms, _n, slowest) in rows.items():
                    self.stdout.write(f"\n{roles[username]}, {name}: {slowest[0]:.1f} ms {slowest[1][:600]}")

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600  # with single sign-on on, an old token would redirect
        session.save()
        return client

    def measure(self, client, url, runs):
        """(fastest time in ms, or the status if the page failed; its SQL time; number of queries; the slowest query)."""
        client.get(url, secure=True)  # the first open also loads templates and fills caches
        best = None
        for _ in range(runs):
            queries = []
            with connection.execute_wrapper(lambda *args: timed(queries, *args)):
                started = time.perf_counter()
                response = client.get(url, secure=True)
                took = (time.perf_counter() - started) * 1000
            if best is None or took < best[0]:
                best = took, queries
        if response.status_code != 200:
            return f"HTTP {response.status_code}", "-", len(best[1]), (0, "")
        took, queries = best
        return round(took), round(sum(ms for ms, _sql in queries)), len(queries), max(queries, default=(0, ""))
