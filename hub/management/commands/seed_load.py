"""Fills an empty database with a year of made-up use by 500 staff, to measure how fast the busy pages stay.

Everything is invented: names put together from short lists, example.com addresses, and file names with no file
behind them. Nobody can sign in as these people (the benchmark command signs in directly), and they get no daily
email. It refuses a database that has any accounts. Run it only on a throwaway database that exists to be measured,
never on the live hub or the test hub (docs/operations/CAPACITY.md).
"""

import random
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from chat.models import Conversation, Membership, Message
from hub.models import (
    NOTIFY_TYPES, RSVP, Attachment, Comment, CommentReaction, Community, Event, FeatureNote, Notification, PollOption,
    PollVote, Post, PostFollow, PostRead, Reaction, Report, User,
)
from library.models import Document, Folder

# A year at Supreme: what --scale 1 makes.
COUNTS = {
    "people": 500, "groups": 60, "posts": 20000, "comments": 100000, "reactions": 100000, "chats": 2000,
    "messages": 50000, "notifications": 30000, "files": 1000,
}
FIRST = (
    "Alex Sam Jordan Casey Morgan Robin Jamie Taylor Charlie Riley Avery Quinn Rowan Elliot Harper Logan Reese Skyler "
    "Drew Emery Finley Hayden Jesse Kai Lane Marley Noel Oakley Parker Remy Sage Tatum Blair Corey Dana Ellis Frankie "
    "Gray Hollis Indy"
).split()
LAST = (
    "Ash Brook Cole Dale Ford Green Hale Irwin Kent Lake Marsh North Oak Pike Reed Stone Thorn Vale Ward West Wood York "
    "Bell Carr Dean Fenn Gale Hart Lord Moss Nash Page Rhodes Shaw Todd Webb Wilde Young Birch Cross"
).split()
DEPARTMENTS = ["Operations", "Sales", "Finance", "Technology", "People", "Marketing", "Facilities", "Customer service"]
LOCATIONS = [("Head office", 70), ("Warehouse", 25), ("Northern depot", 5)]  # (name, share of staff in %)
HOBBIES = (
    "Running Cycling Book Photography Gardening Cooking Football Charity Gaming Music Film Parents Wellbeing Chess "
    "Hiking Baking Coffee Pets Climbing Yoga"
).split()
WORDS = (
    "team week update thanks shift delivery customer order stock warehouse office meeting plan project report safety "
    "training lunch coffee parking rota holiday welcome great news today tomorrow please everyone new client target "
    "monthly results kitchen printer laptop system change review question help support well done busy morning"
).split()
REACTIONS = [("like", 60), ("love", 15), ("celebrate", 12), ("laugh", 8), ("wow", 3), ("sad", 2)]
BATCH = 2000


def text(rnd, low, high):
    return " ".join(rnd.choices(WORDS, k=rnd.randint(low, high))).capitalize() + "."


def popularity(rnd, n, cap=300):
    """How much attention each of n items gets: most get a little, a few get a lot (as in any real feed)."""
    return [min(rnd.paretovariate(1.3), cap) for _ in range(n)]


def spread(rnd, total, weights, most):
    """Split total over len(weights) items in proportion to weights, at most `most` each."""
    picks = rnd.choices(range(len(weights)), weights=weights, k=total)
    counts = [0] * len(weights)
    for i in picks:
        counts[i] += 1
    return [min(c, most) for c in counts]


def after(rnd, start, now, mean_hours):
    """A moment a little after start (mostly within mean_hours), never in the future."""
    moment = start + timedelta(hours=rnd.expovariate(1 / mean_hours))
    # Not simply capped at now: the newest posts' comments would all share one time, and "newest" would mean nothing.
    return moment if moment < now else start + (now - start) * rnd.random()


class Command(BaseCommand):
    help = "Fill an empty database with a year of made-up use by 500 staff, to measure speed (never on a live system)."

    def add_arguments(self, parser):
        parser.add_argument("--scale", type=float, default=1.0, help="Multiply every amount, e.g. 0.1 for a quick try.")
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off (a throwaway Postgres).")

    def handle(self, *args, **options):
        if not (settings.DEBUG or options["force"]):
            raise CommandError("seed_load is for a throwaway copy of the hub. Use --force there, never on the live or test hub.")
        # No migration makes accounts, so an empty database has none. A live hub has staff even before its first post.
        if User.objects.exists():
            raise CommandError("The database already has people; seed_load only fills an empty one.")
        self.n = {key: max(1, round(value * options["scale"])) for key, value in COUNTS.items()}
        self.n["people"] = max(self.n["people"], 20)  # enough for group chats and the two benchmark accounts
        self.rnd, self.now, started = random.Random(27), timezone.now(), time.monotonic()
        with transaction.atomic():
            self.people()
            self.communities()
            self.posts()
            self.comments_and_reactions()
            self.chats()
            self.notifications()
            self.files()
        took = time.monotonic() - started
        made = ", ".join(f"{model._meta.verbose_name_plural}: {model.objects.count()}" for model in (
            User, Community, Post, Comment, Reaction, Conversation, Message, Notification, Document))
        self.stdout.write(self.style.SUCCESS(f"Done in {took:.0f} s. {made}."))

    def bulk(self, model, rows):
        return model.objects.bulk_create(rows, batch_size=BATCH)

    # --- People and where they belong -----------------------------------------------------------

    def people(self):
        rnd, today = self.rnd, timezone.localdate()
        no_password = make_password(None)  # nobody signs in as these people
        rows = []
        for i in range(self.n["people"]):
            first, last = rnd.choice(FIRST), rnd.choice(LAST)
            # Two fixed accounts for the benchmark: a moderator who sees everything, and an ordinary colleague.
            username = {0: "load-admin", 1: "load-user"}.get(i, f"load{i:04d}")
            rows.append(User(
                username=username, email=f"{username}@example.com", password=no_password, first_name=first,
                last_name=last, department=rnd.choice(DEPARTMENTS), job_title=text(rnd, 1, 2)[:-1],
                is_staff=i == 0, is_superuser=i == 0, policy_version=settings.POLICY_VERSION, email_digest=False,
                start_date=today - timedelta(days=rnd.randint(10, 4000)),
                birthday=(today - timedelta(days=rnd.randint(0, 365))).replace(year=2000) if rnd.random() < 0.3 else None,
                last_seen=self.now - timedelta(minutes=rnd.randint(0, 60 * 24 * 7)), date_joined=self.now - timedelta(days=365),
            ))
        self.users = self.bulk(User, rows)
        self.admin, self.user = self.users[0], self.users[1]
        # A few people write most of the posts, as in any company.
        self.voice = [1 / (rank + 1) ** 0.7 for rank in range(len(self.users))]
        rnd.shuffle(self.voice)

    def communities(self):
        rnd, users = self.rnd, self.users
        units = [Community(name=name, slug=f"load-{name.lower().replace(' ', '-')}", kind=Community.UNIT, unit_type="location")
                 for name, _share in LOCATIONS]
        units += [Community(name=name, slug=f"load-{name.lower().replace(' ', '-')}", kind=Community.UNIT, unit_type="department")
                  for name in DEPARTMENTS]
        units = self.bulk(Community, units)
        locations, departments = units[:len(LOCATIONS)], {u.name: u for u in units[len(LOCATIONS):]}
        teams = self.bulk(Community, [
            Community(name=f"{dept} team {n}", slug=f"load-{dept.lower().replace(' ', '-')}-team-{n}", kind=Community.UNIT,
                      unit_type="team", parent=departments[dept])
            for dept in DEPARTMENTS for n in (1, 2)
        ])
        groups = []
        for i in range(self.n["groups"]):
            name = f"{HOBBIES[i % len(HOBBIES)]} club" + (f" {i // len(HOBBIES) + 1}" if i >= len(HOBBIES) else "")
            groups.append(Community(name=name, slug=f"load-{name.lower().replace(' ', '-')}", kind=Community.GROUP,
                                    is_private=i % 4 == 3, description=text(rnd, 6, 20), created_by=rnd.choice(users)))
        self.groups = self.bulk(Community, groups)

        Member = Community.members.through
        members, admins = [], []
        shares = [share for _name, share in LOCATIONS]
        self.mine = {u.pk: set() for u in users}  # user id -> ids of their groups and units
        for user in users:
            team = rnd.choice([t for t in teams if t.parent_id == departments[user.department].pk])
            for unit in (rnd.choices(locations, weights=shares)[0], departments[user.department], team):
                members.append(Member(community_id=unit.pk, user_id=user.pk))
                self.mine[user.pk].add(unit.pk)
        for rank, group in enumerate(self.groups):
            size = min(len(users), max(5, round(len(users) * 0.8 / (rank + 1) ** 0.8)))
            chosen = rnd.sample(users, size)
            if rank == 0:  # the benchmark's two accounts are in the busiest group
                chosen += [u for u in (self.user, self.admin) if u not in chosen]
            for user in chosen:
                members.append(Member(community_id=group.pk, user_id=user.pk))
                self.mine[user.pk].add(group.pk)
            admins += [Community.admins.through(community_id=group.pk, user_id=u.pk) for u in chosen[:2]]
        self.bulk(Member, members)
        self.bulk(Community.admins.through, admins)
        self.units = units + teams
        self.unit_ids = {u.pk for u in self.units}

    # --- Posts, news, polls and events -----------------------------------------------------------

    def posts(self):
        rnd, now, users = self.rnd, self.now, self.users
        total = self.n["posts"]
        news_n, poll_n, event_n = max(1, total // 50), max(1, total // 50), max(1, total * 3 // 200)
        kinds = [Post.NEWS] * news_n + [Post.POLL] * poll_n + [Post.EVENT] * event_n
        kinds += [Post.UPDATE] * (total - len(kinds))
        rnd.shuffle(kinds)

        events = []
        for _ in range(event_n):
            starts = now + timedelta(days=rnd.uniform(-335, 30), hours=rnd.randint(-3, 3))
            group = rnd.choice(self.groups) if rnd.random() < 0.2 else None
            events.append(Event(title=text(rnd, 2, 5)[:-1], description=text(rnd, 10, 40), location=text(rnd, 1, 3)[:-1],
                                starts_at=starts, ends_at=starts + timedelta(hours=2), community=group,
                                created_by=rnd.choice(users)))
        events = iter(self.bulk(Event, events))

        rows = []
        for kind in kinds:
            author = rnd.choices(users, weights=self.voice)[0]
            when = now - timedelta(days=rnd.uniform(0, 365))
            post = Post(kind=kind, author=author, created_at=when, last_activity_at=when, notified_at=when)
            if kind == Post.EVENT:
                post.event = next(events)
                post.community = post.event.community
                post.created_at = post.last_activity_at = post.notified_at = min(when, post.event.starts_at)
            elif kind == Post.NEWS:
                post.title, post.body = text(rnd, 3, 8)[:-1], "\n\n".join(text(rnd, 30, 80) for _ in range(3))
                post.requires_ack = rnd.random() < 0.1
            else:
                post.body = text(rnd, 8, 60)
                place = rnd.random()
                mine = sorted(self.mine[author.pk])
                if place < 0.3:
                    post.community_id = rnd.choice([c for c in mine if c in self.unit_ids])
                elif place < 0.55 and any(c not in self.unit_ids for c in mine):
                    post.community_id = rnd.choice([c for c in mine if c not in self.unit_ids])
            if kind == Post.UPDATE and rnd.random() < 0.05:
                post.body += f" Thanks @{rnd.choice(users).get_full_name()}!"
            post.is_hidden = rnd.random() < 0.003
            post.deleted_at = now if rnd.random() < 0.005 else None
            rows.append(post)
        rows.sort(key=lambda p: p.created_at)  # ids follow time, as in real use
        # Company announcements and team news get pinned, and draw the most attention.
        for post in [p for p in rows if p.community_id is None and p.kind in (Post.UPDATE, Post.NEWS)][-5:]:
            post.pinned_at, post.is_announcement = post.created_at, post.kind == Post.UPDATE
        for post in [p for p in rows if p.community_id in {g.pk for g in self.groups}][-10:]:
            post.pinned_at = post.created_at
        # The benchmark user has a draft and two posts waiting to go out.
        rows += [Post(author=self.user, body=text(rnd, 8, 20), is_draft=True),
                 *(Post(author=self.user, body=text(rnd, 8, 20), created_at=now + timedelta(days=d)) for d in (1, 3))]
        made = self.bulk(Post, rows)
        self.live = [p for p in made if p.is_live]

        news = [p for p in made if p.kind == Post.NEWS]
        Audience = Post.audiences.through
        self.bulk(Audience, [Audience(post_id=p.pk, community_id=c.pk)
                             for p in news if rnd.random() < 0.3 for c in rnd.sample(self.units, rnd.randint(1, 2))])
        mentions = []
        names = {u.get_full_name(): u for u in users}
        for post in made:
            if "@" in post.body:
                mentions.append(Post.mentions.through(post_id=post.pk, user_id=names[post.body.split("@")[1][:-1]].pk))
        self.bulk(Post.mentions.through, mentions)
        self.bulk(Attachment, [
            Attachment(post=p, file=f"posts/{p.created_at:%Y/%m}/load-{p.pk}-{n}.jpg", kind=Attachment.IMAGE)
            for p in made if p.kind == Post.UPDATE and rnd.random() < 0.15 for n in range(rnd.randint(1, 4))
        ])

        polls = [p for p in made if p.kind == Post.POLL]
        options = self.bulk(PollOption, [PollOption(post=p, text=text(rnd, 1, 4)[:-1], position=n)
                                         for p in polls for n in range(rnd.randint(2, 5))])
        by_poll = {}
        for option in options:
            by_poll.setdefault(option.post_id, []).append(option)
        self.bulk(PollVote, [PollVote(post_id=p.pk, option=rnd.choice(by_poll[p.pk]), user=u)
                             for p in polls for u in rnd.sample(users, min(len(users), rnd.randint(20, 150)))])
        self.bulk(PostRead, [
            PostRead(post=p, user=u, read_at=after(rnd, p.created_at, now, 24),
                     acknowledged_at=p.created_at if p.requires_ack and rnd.random() < 0.8 else None)
            for p in news if p.is_live for u in rnd.sample(users, round(len(users) * rnd.uniform(0.4, 0.8)))
        ])
        rsvps = [RSVP(event_id=p.event_id, user=u, status=rnd.choice(RSVP.Status.values))
                 for p in made if p.event_id for u in rnd.sample(users, min(len(users), rnd.randint(5, 60)))]
        self.bulk(RSVP, rsvps)
        follows = {(rnd.choice(self.live).pk, rnd.choice(users).pk) for _ in range(len(made) // 7)}
        self.bulk(PostFollow, [PostFollow(post_id=p, user_id=u) for p, u in follows])
        self.bulk(FeatureNote, [FeatureNote(title=text(rnd, 2, 4)[:-1], body=text(rnd, 15, 30),
                                            published_at=now - timedelta(days=30 * n)) for n in range(6)])

    def comments_and_reactions(self):
        rnd, now, users, live = self.rnd, self.now, self.users, self.live
        weights = popularity(rnd, len(live))
        for i, post in enumerate(live):
            if post.pinned_at:
                weights[i] = 300  # pinned announcements are what everyone comments on
        top_n = round(self.n["comments"] * 0.8)
        top = []
        for post, count in zip(live, spread(rnd, top_n, weights, 1000)):
            top += [Comment(post=post, author=rnd.choice(users), body=text(rnd, 2, 25), created_at=after(rnd, post.created_at, now, 12))
                    for _ in range(count)]
        top.sort(key=lambda c: c.created_at)
        top = self.bulk(Comment, top)
        # Most replies land here and there. The newest thread under each pinned post is a long conversation of 60 to
        # 200, which the feed and the busiest post show.
        newest = {c.post_id: c for c in top if c.post.pinned_at}  # top is sorted by time, so the newest one stays
        parents = [c for c in newest.values() for _ in range(rnd.randint(60, 200))][:self.n["comments"] - top_n]
        parents += rnd.choices(top, k=self.n["comments"] - top_n - len(parents))
        replies = [Comment(post_id=parent.post_id, parent=parent, author=rnd.choice(users), body=text(rnd, 2, 15),
                           created_at=after(rnd, parent.created_at, now, 6)) for parent in parents]
        replies.sort(key=lambda c: c.created_at)
        comments = top + self.bulk(Comment, replies)
        latest = {}
        for comment in comments:
            latest[comment.post_id] = max(latest.get(comment.post_id, comment.created_at), comment.created_at)
        for post in live:
            post.last_activity_at = latest.get(post.pk, post.created_at)
        Post.objects.bulk_update(live, ["last_activity_at"], batch_size=BATCH)

        kinds, odds = zip(*REACTIONS)
        rows = []
        for post, count in zip(live, spread(rnd, self.n["reactions"], weights, len(users))):
            rows += [Reaction(post=post, user=u, kind=rnd.choices(kinds, odds)[0]) for u in rnd.sample(users, count)]
        self.bulk(Reaction, rows)
        liked = {(rnd.choice(comments).pk, rnd.choice(users).pk) for _ in range(self.n["comments"] // 5)}
        self.bulk(CommentReaction, [CommentReaction(comment_id=c, user_id=u, kind="like") for c, u in liked])
        self.bulk(Report, [Report(reporter=rnd.choice(users), comment=rnd.choice(comments), reason=text(rnd, 5, 15),
                                  resolved_at=now if n % 2 else None) for n in range(40)])

    # --- Chat, alerts and files ---------------------------------------------------------------------

    def chats(self):
        rnd, now, users = self.rnd, self.now, self.users
        conversations, people = [], []
        pairs = {(self.admin.pk, self.user.pk)}  # so both benchmark accounts have a chat to open
        while len(pairs) < round(self.n["chats"] * 0.85):
            a, b = sorted(rnd.sample(range(len(users)), 2))
            pairs.add((users[a].pk, users[b].pk))
        for low, high in sorted(pairs):
            conversations.append(Conversation(pair=f"{low}:{high}", created_at=now - timedelta(days=rnd.uniform(1, 365))))
            people.append([low, high])
        for _ in range(self.n["chats"] - len(pairs)):
            chosen = [u.pk for u in rnd.sample(users, rnd.randint(3, min(15, len(users))))]
            conversations.append(Conversation(is_group=True, name=text(rnd, 1, 3)[:-1], created_by_id=chosen[0],
                                              created_at=now - timedelta(days=rnd.uniform(1, 365))))
            people.append(chosen)
        conversations = self.bulk(Conversation, conversations)

        messages = []
        for chat, who, count in zip(conversations, people, spread(rnd, self.n["messages"], popularity(rnd, len(conversations)), 5000)):
            moments = sorted(chat.created_at + (now - chat.created_at) * rnd.random() for _ in range(count))
            messages += [Message(conversation=chat, sender_id=rnd.choice(who), body=text(rnd, 1, 20), created_at=when,
                                 image=f"chat/{when:%Y/%m}/load-{len(messages)}-{n}.jpg" if rnd.random() < 0.02 else "",
                                 deleted_at=now if rnd.random() < 0.01 else None)
                         for n, when in enumerate(moments)]
            chat.last_message_at = moments[-1] if moments else None
        messages.sort(key=lambda m: m.created_at)
        self.bulk(Message, messages)
        Conversation.objects.bulk_update(conversations, ["last_message_at"], batch_size=BATCH)
        self.bulk(Membership, [
            Membership(conversation=chat, user_id=pk, joined_at=chat.created_at,
                       # Most people have read everything; one in five has something new waiting.
                       last_read_at=(chat.last_message_at or chat.created_at) - timedelta(hours=6 if rnd.random() < 0.2 else 0))
            for chat, who in zip(conversations, people) for pk in who
        ])

    def notifications(self):
        rnd, now, users = self.rnd, self.now, self.users
        categories = [*NOTIFY_TYPES, "messages"]
        rows = []
        for _ in range(self.n["notifications"]):
            post, when = rnd.choice(self.live), now - timedelta(days=rnd.uniform(0, 90))  # older alerts are purged
            seen = rnd.random() < 0.85
            rows.append(Notification(
                recipient=rnd.choice(users), actor=rnd.choice(users), category=rnd.choice(categories), message=text(rnd, 4, 10),
                url=post.get_absolute_url(), created_at=when, read_at=after(rnd, when, now, 8) if seen else None, pushed_at=when,
            ))
        self.bulk(Notification, rows)

    def files(self):
        rnd, now, users = self.rnd, self.now, self.users
        folders = self.bulk(Folder, [Folder(name=text(rnd, 1, 2)[:-1], community=rnd.choice(self.groups) if n % 3 == 2 else None)
                                     for n in range(40)])
        rows = []
        for n in range(self.n["files"]):
            folder = rnd.choice(folders)
            when = now - timedelta(days=rnd.uniform(0, 365))
            rows.append(Document(folder=folder, community=folder.community, title=text(rnd, 2, 6)[:-1],
                                 file=f"library/{when:%Y/%m}/load-{n}.pdf", original_name=f"load-{n}.pdf",
                                 size=rnd.randint(20_000, 5_000_000), uploaded_by=rnd.choice(users), created_at=when,
                                 is_featured=rnd.random() < 0.02))
        self.bulk(Document, rows)
