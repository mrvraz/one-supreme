"""Fills an empty database with made-up colleagues, teams, groups, news, posts and events for demos.

Locally (DEBUG on) every demo account uses the password in DEMO_PASSWORD. On a demo server (--force) nobody
can sign in as these people; demo_logins creates the sign-ins. Demo data only: never run this on a live system.
"""

import random
import re
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image, ImageDraw, ImageOps

from chat.models import Conversation, Membership, Message
from hub.models import (
    RSVP, Attachment, Comment, CommentReaction, Community, Event, FeatureNote, PollOption, PollVote, Post, PostRead,
    Reaction, User, notify,
)
from hub.publishing import set_mentions
from jobs.models import Interest, Vacancy
from journeys.models import Journey, Step, StepDone, assign
from library.models import Article, Category, Document, FeaturedLink, Folder

DEMO_PASSWORD = "demo-hub-2026"

# first, last, job title, department, birthday in (days from today) or None, years at the company,
# days until their work anniversary, pronouns
PEOPLE = [
    ("Amelia", "Hughes", "Head of People", "People", None, 8, 40, "she/her"),
    ("Oliver", "Bennett", "Software Engineer", "Technology", 0, 3, 120, "he/him"),
    ("Priya", "Shah", "Finance Manager", "Finance", 3, 6, 200, ""),
    ("James", "O'Connor", "Warehouse Supervisor", "Operations", None, 12, 2, "he/him"),
    ("Sophie", "Clarke", "Internal Communications Lead", "Marketing", 9, 4, 75, "she/her"),
    ("Daniel", "Okafor", "Account Director", "Sales", None, 5, 300, ""),
    ("Grace", "Turner", "Office Manager", "Facilities", 21, 10, 6, "she/her"),
    ("Mohammed", "Ali", "Data Analyst", "Technology", None, 2, 160, ""),
    ("Emily", "Walsh", "Customer Success", "Sales", 45, 1, 250, "she/her"),
    ("Tom", "Fletcher", "Health & Safety Officer", "Operations", None, 7, 90, "he/him"),
    ("Hannah", "Price", "Graphic Designer", "Marketing", None, 0, 30, "she/her"),  # started this month
    ("Liam", "Doyle", "IT Support", "Technology", None, 0, 20, "he/him"),
]

# Locations of the organisation: (name, who works there)
LOCATIONS = [("Manchester office", lambda p: p[3] != "Operations"), ("Warehouse", lambda p: p[3] == "Operations")]

# Groups: (name, description, private?)
GROUPS = [
    ("Running Club", "Lunchtime 5k loops and weekend parkruns. All paces welcome.", False),
    ("Book Club", "One book a month, discussed over coffee on the last Thursday.", False),
    ("Charity & Volunteering", "Fundraisers, volunteering days and this year's charity of the year.", False),
    ("Photography", "Share your best shots. Monthly theme announced on the first Monday.", False),
    ("Leadership team", "Private space for the leadership team.", True),
]

# (author index, team or group name or None, text, photos, hours ago, pinned?)
POSTS = [
    (0, None, "Welcome to our new staff hub! 🎉 This is the place for team news, photos and events.\n\n"
              "- Say hello in the comments\n- Join a few groups\n- Turn on notifications in **Settings**", 1, 2, True),
    (4, None, "What a turnout at Friday's summer social. Thanks to everyone who came, and to @Grace Turner "
              "for organising the food!", 2, 5, False),
    (1, "Technology", "Heads up: the VPN gets an upgrade on Saturday morning from 8 to 10. You may need to "
                      "sign in again afterwards.", 0, 9, False),
    (3, "Warehouse", "Huge well done to the warehouse team. **30 days** without a single safety incident. 💪", 1, 20, False),
    (6, "Manchester office", "The 3rd floor kitchen has a new coffee machine. Please be kind to it.", 1, 26, False),
    (2, "Charity & Volunteering", "We raised £2,340 at the bake sale for the children's hospice. Thank you all!", 1, 30, False),
    (7, "Photography", "Lovely sunrise on the commute this morning.", 1, 44, False),
    (5, None, "Just signed our biggest client of the year. Thanks to everyone in sales and "
              "operations who helped get it over the line.", 0, 52, False),
    (8, "Running Club", "Who's up for the Sunday parkrun? Meeting at the café at 8:45.", 0, 60, True),
    (10, "Book Club", "This month's pick is in: a short, gripping novel. Copies are on the shelf by reception.", 1, 70, False),
    (0, "Leadership team", "Draft budget for next year is in the shared folder. Comments by Friday please.", 0, 30, False),
]

COMMENTS = [
    "Great news!", "Love this 😄", "Count me in.", "Thanks for sharing!", "Brilliant work everyone.",
    "See you there!", "This made my day.", "Well deserved 👏",
]
REPLIES = ["Agreed!", "Thank you 😊", "Same here.", "Ha, yes!"]

# (author index, title, text, hours ago (negative: scheduled), audience unit or None, must read?, draft?)
NEWS = [
    (4, "Our new staff hub is live", "Everything in one place: news, groups, events, chat and the people "
        "directory. Have a look around and tell us what you think.", 3, None, False, False),
    (9, "Updated fire safety procedure", "We've changed the assembly point for the Manchester office to the "
        "car park on the north side.\n\n1. Leave by the nearest exit\n2. Don't use the lifts\n3. Report to your "
        "fire warden\n\nPlease confirm below that you've read this.", 28, None, True, False),
    (3, "Warehouse rota for the holiday period", "The rota for the last two weeks of December is up on the "
        "noticeboard and in Files. Swaps go through James.", 50, "Operations", False, False),
    (4, "Winter party: save the date", "Details to follow, but put the date in your diary now.", -48, None, False, False),
    (4, "Benefits update", "New cycle-to-work scheme partner. Details to confirm with Finance.", 1, None, False, True),
]

# (title, description, location, days from now, group name or None)
EVENTS = [
    ("Summer social", "Drinks, food and lawn games on the terrace.", "Terrace, 5th floor", 6, None),
    ("Sunday parkrun", "5k at the park, coffee after.", "Heaton Park café", 4, "Running Club"),
    ("Book club: monthly chat", "Bring your thoughts and a mug.", "Meeting room 2", 15, "Book Club"),
    ("Volunteering day", "Helping at the local food bank. Lunch provided.", "City food bank", 21, "Charity & Volunteering"),
    ("All-hands meeting", "Quarterly update from the leadership team, with Q&A.", "Main hall and Teams", 9, None),
]

FEATURE_NOTES = [
    ("News with must-read", "Important news can ask readers to confirm they've read it. The author sees "
                            "who has and who hasn't.", 1),
    ("Polls", "Ask a question in the feed and see the results live. Polls can close on a date you choose.", 3),
    ("Do not disturb", "Pause notifications from the Menu, or set quiet hours and weekends in Settings.", 6),
]


# Which stock photo each demo picture uses (see ../demo_photos/CREDITS.txt). Keys are the seeds below:
# post n's photos are n*10, n*10+1…; news covers 300+n; the journey cover 700.
PHOTOS = {
    0: "office", 10: "social", 11: "food", 30: "warehouse", 40: "coffee", 50: "cakes", 60: "sunrise", 90: "books",
    300: "laptop", 301: "exit", 302: "warehouse", 303: "lights", 304: "bikes", 700: "laptop",
}
PHOTO_DIR = Path(__file__).resolve().parent.parent / "demo_photos"
SIZES = {"file": (1200, 900), "news": (1200, 630), "journey": (1200, 500)}


def picture(seed, size=SIZES["file"]):
    """A stock photo standing in for one a colleague would upload, cropped to size."""
    img = ImageOps.fit(Image.open(PHOTO_DIR / f"{PHOTOS[seed]}.jpg").convert("RGB"), size)
    out = BytesIO()
    img.save(out, "JPEG", quality=82)
    return ContentFile(out.getvalue(), name=f"demo-{seed}-photo.jpg")  # a new name, so browsers drop the old picture


def pdf(title):
    """A one-page PDF with just a title, standing in for a real document."""
    out = BytesIO()
    page = Image.new("RGB", (850, 1100), "white")
    ImageDraw.Draw(page).text((80, 80), title, fill="black")
    page.save(out, "PDF")
    return ContentFile(out.getvalue(), name=f"{title.lower().replace(' ', '-')}.pdf")


def years_before(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February in a year without one
        return day.replace(year=day.year - years, day=28)


def slug(name):
    return name.lower().replace(" & ", "-").replace(" ", "-")


class Command(BaseCommand):
    help = "Create demo colleagues, teams, groups, news, posts and events (for demos and development only)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off (demo servers).")
        parser.add_argument("--refresh-pictures", action="store_true",
                            help="Give an already seeded demo today's demo pictures, keeping everything else.")

    def handle(self, *args, **options):
        if not (settings.DEBUG or options["force"]):
            raise CommandError("seed_demo is for demos only. Use --force on a demo server, never on a live system.")
        if options["refresh_pictures"]:
            return self.refresh_pictures()
        if Post.objects.exists():
            raise CommandError("The database already has posts; seed_demo only fills an empty one.")

        rnd = random.Random(42)
        now = timezone.now()
        people = self.people(timezone.localdate())
        places = self.organisation(people)
        self.groups(people, places, rnd)
        self.posts(people, places, rnd, now)
        self.news(people, places, now)
        self.poll(people, rnd, now)
        self.events(people, places, rnd, now)
        for title, body, days in FEATURE_NOTES:
            FeatureNote.objects.create(title=title, body=body, published_at=now - timedelta(days=days))
        self.library(people, places)
        self.journeys(people)
        self.jobs(people, timezone.localdate())
        self.chat(people, now)

        self.stdout.write(self.style.SUCCESS(
            f"Created {len(people)} people, {Community.objects.count()} teams and groups, "
            f"{Post.objects.count()} posts and news, and {Event.objects.count()} events. "
            + ("Sign in as 'amelia' (admin), 'sophie' (publishes news) or any first name, e.g. 'oliver'. "
               "Password: see DEMO_PASSWORD in seed_demo.py." if settings.DEBUG else
               "These colleagues can't sign in here; create sign-ins with demo_logins.")
        ))

    def refresh_pictures(self):
        """Swap the pictures seed_demo made (files named demo-<seed>.jpg) for today's, in place, so a running demo
        keeps its sign-ins, posts and comments. Groups lose theirs: a new group starts without a photo."""
        made_here = re.compile(r"demo-(\d+)(?:-photo)?(?:_\w+)?\.jpg$")  # storage adds _abc1234 when a name is taken
        swapped = removed = 0
        for model, field, size in ((Attachment, "file", SIZES["file"]), (Post, "cover", SIZES["news"]),
                                   (Journey, "cover", SIZES["journey"]), (Community, "cover", None)):
            for obj in model.objects.exclude(**{field: ""}):
                file = getattr(obj, field)
                found = made_here.search(file.name)
                if not found:
                    continue  # uploaded by a person: leave it alone
                seed = int(found.group(1))
                new = picture(seed, size) if size and seed in PHOTOS else None  # made first: a failure keeps the old one
                file.delete(save=False)
                if new is not None:
                    file.save(new.name, new, save=False)
                    model.objects.filter(pk=obj.pk).update(**{field: file.name})  # update(): no save() side effects
                    swapped += 1
                    continue
                if model is Attachment:
                    obj.delete()  # a post had more demo photos than it has now
                else:
                    model.objects.filter(pk=obj.pk).update(**{field: ""})
                removed += 1
        self.stdout.write(self.style.SUCCESS(f"Swapped {swapped} demo pictures and removed {removed}."))

    def people(self, today):
        people = []
        for i, (first, last, title, dept, birthday_in, years, anniversary_in, pronouns) in enumerate(PEOPLE):
            birthday = today + timedelta(days=birthday_in) if birthday_in is not None else None
            if years:
                started = years_before(today + timedelta(days=anniversary_in), years)
            else:
                started = today - timedelta(days=anniversary_in)  # new starters: joined in the last few weeks
            people.append(User.objects.create_user(
                username=first.lower(),
                email=f"{first}.{last}@example.com".lower().replace("'", ""),
                # The password is in this file, so it only works locally; demo servers use demo_logins.
                password=DEMO_PASSWORD if settings.DEBUG else None,
                first_name=first,
                last_name=last,
                job_title=title,
                department=dept,
                pronouns=pronouns,
                languages="English" + (", Hindi" if first == "Priya" else ", Arabic" if first == "Mohammed" else ""),
                birthday=birthday.replace(year=2000) if birthday else None,  # opt-in; the year is never kept
                start_date=started,
                is_staff=i == 0,
                is_superuser=i == 0,  # Amelia is the demo admin and moderator
            ))
        # Sophie runs internal communications: she can publish news.
        people[4].user_permissions.add(Permission.objects.get(codename="publish_news"))
        return people

    def organisation(self, people):
        admin = people[0]
        head_office = Community.objects.create(
            name="Head Office", slug="head-office", kind=Community.UNIT, unit_type="business",
            description="Everyone at head office.", created_by=admin,
        )
        head_office.members.add(*people)
        places = {}
        for dept in dict.fromkeys(row[3] for row in PEOPLE):
            unit = Community.objects.create(
                name=dept, slug=slug(dept), kind=Community.UNIT, unit_type="department", parent=head_office,
                description=f"The {dept} department.", created_by=admin,
            )
            unit.members.add(*[person for person, row in zip(people, PEOPLE) if row[3] == dept])
            places[dept] = unit
        for name, works_there in LOCATIONS:
            unit = Community.objects.create(
                name=name, slug=slug(name), kind=Community.UNIT, unit_type="location", parent=head_office,
                description=f"News and notices for the {name.lower()}.", created_by=admin,
            )
            unit.members.add(*[person for person, row in zip(people, PEOPLE) if works_there(row)])
            places[name] = unit
        head_office.admins.add(admin)
        for unit in places.values():
            unit.admins.add(admin)
        return places

    def groups(self, people, places, rnd):
        for i, (name, description, private) in enumerate(GROUPS):
            creator = people[0] if private else people[i + 1]
            group = Community.objects.create(
                name=name, slug=slug(name), description=description, is_private=private, created_by=creator,
            )  # no cover: new groups show their letter until an admin adds a photo
            members = [people[2], people[5]] if private else rnd.sample(people, rnd.randint(5, 10))
            group.members.add(creator, *members)
            group.admins.add(creator)
            places[name] = group

    def posts(self, people, places, rnd, now):
        for n, (author, place, text, photos, hours, pinned) in enumerate(POSTS):
            created = now - timedelta(hours=hours)
            post = Post.objects.create(
                author=people[author], community=places[place] if place else None, body=text,
                is_announcement=pinned and place is None, pinned_at=created if pinned else None,
                created_at=created, last_activity_at=created, notified_at=created,
            )
            if post.community:
                post.community.members.add(post.author)
            set_mentions(post)
            for p in range(photos):
                Attachment.objects.create(post=post, file=picture(n * 10 + p), kind=Attachment.IMAGE, alt_text="")
            audience = list(post.community.members.all()) if post.community else people
            for person in rnd.sample(audience, min(len(audience), rnd.randint(2, 9))):
                Reaction.objects.create(post=post, user=person, kind=rnd.choice(Reaction.Kind.values))
            when = created
            for c in range(rnd.randint(0, 3)):
                when = created + timedelta(minutes=20 * (c + 1))
                comment = Comment.objects.create(post=post, author=rnd.choice(audience), body=rnd.choice(COMMENTS), created_at=when)
                if c == 0:  # the first comment gets a like and a reply from the author
                    CommentReaction.objects.create(comment=comment, user=post.author, kind="like")
                    when += timedelta(minutes=5)
                    Comment.objects.create(post=post, author=post.author, parent=comment, body=rnd.choice(REPLIES), created_at=when)
            Post.objects.filter(pk=post.pk).update(last_activity_at=when)
        # Something waiting in the bell for the demo admin.
        welcome = Post.objects.filter(author=people[0], community=None).first()
        url = welcome.get_absolute_url()
        notify([people[0]], people[1], f"{people[1].get_full_name()} commented on your post", url, category="comments")
        notify([people[0]], people[4], f"{people[4].get_full_name()} mentioned you in a post", url, category="mentions")

    def news(self, people, places, now):
        for n, (author, title, text, hours, audience, must_read, draft) in enumerate(NEWS):
            created = now - timedelta(hours=hours)
            live = not draft and hours > 0  # scheduled and draft news are announced when they go live
            post = Post.objects.create(
                kind=Post.NEWS, author=people[author], title=title, body=text, cover=picture(300 + n, SIZES["news"]),
                is_announcement=True, requires_ack=must_read, is_draft=draft, created_at=created,
                last_activity_at=created, notified_at=created if live else None,
            )
            if audience:
                post.audiences.set([places[audience]])
            if must_read:
                for person in people[:7]:
                    PostRead.objects.create(post=post, user=person, read_at=created, acknowledged_at=created + timedelta(hours=1))
                for person in people[7:9]:
                    PostRead.objects.create(post=post, user=person, read_at=created)

    def poll(self, people, rnd, now):
        created = now - timedelta(hours=12)
        poll = Post.objects.create(
            kind=Post.POLL, author=people[6], body="Where should we hold the winter party?",
            poll_closes_at=now + timedelta(days=5), created_at=created, last_activity_at=created, notified_at=created,
        )
        options = [PollOption.objects.create(post=poll, text=text, position=i)
                   for i, text in enumerate(["The rooftop bar", "Bowling and pizza", "The usual pub"])]
        for person in people[1:10]:
            PollVote.objects.create(post=poll, option=rnd.choice(options), user=person)

    def events(self, people, places, rnd, now):
        for title, description, location, days, group in EVENTS:
            starts = (now + timedelta(days=days)).replace(hour=17 if group is None else 9, minute=30, second=0, microsecond=0)
            event = Event.objects.create(
                title=title, description=description, location=location, starts_at=starts,
                ends_at=starts + timedelta(hours=2), community=places[group] if group else None,
                created_by=rnd.choice(people),
            )
            created = now - timedelta(hours=days)
            Post.objects.create(
                kind=Post.EVENT, author=event.created_by, community=event.community, event=event,
                created_at=created, last_activity_at=created, notified_at=created,
            )
            audience = list(event.community.members.all()) if event.community else people
            for person in rnd.sample(audience, min(len(audience), rnd.randint(3, 8))):
                RSVP.objects.create(event=event, user=person, status=rnd.choice(RSVP.Status.values))

    def library(self, people, places):
        admin = people[0]
        policies = Folder.objects.create(name="Policies", created_by=admin)
        forms = Folder.objects.create(name="HR forms", created_by=admin)
        for folder, community, title, featured, by in [
            (policies, None, "Staff handbook", True, admin), (policies, None, "Expenses policy", False, admin),
            (forms, None, "Holiday request form", True, admin), (None, None, "Office floor plan", False, admin),
            (None, places["Operations"], "Holiday rota", False, people[3]),
        ]:
            file = pdf(title)
            Document.objects.create(
                folder=folder, community=community, title=title, file=file, original_name=file.name, size=file.size,
                uploaded_by=by, is_featured=featured,
            )
        for i, (title, url) in enumerate([
            ("Payslips and pensions", "https://example.com/payslips"),
            ("IT help desk", "https://example.com/it-help"),
            ("Book a desk", "https://example.com/desks"),
        ]):
            FeaturedLink.objects.create(title=title, url=url, position=i, created_by=admin)
        it = Category.objects.create(name="IT help", position=1)
        hr = Category.objects.create(name="HR and benefits", position=2)
        policies_kb = Category.objects.create(name="Policies", position=3)
        for category, title, body, is_legal in [
            (it, "Resetting your password", "1. Go to the sign-in page\n2. Choose **Forgot password**\n3. Follow the email", False),
            (it, "Connecting to the office Wi-Fi", "Pick the *Staff* network and sign in with your work account.", False),
            (hr, "Booking holiday", "Use the holiday request form in **Files**, then tell your manager.", False),
            (policies_kb, "Acceptable use policy", "Use the hub for work and friendly chat. Be kind, and keep customer data out of it.", True),
        ]:
            Article.objects.create(category=category, title=title, body=body, is_legal=is_legal, created_by=admin, updated_by=admin)

    def journeys(self, people):
        journey = Journey.objects.create(
            title="Your first week", description="Everything you need in your first five days.",
            cover=picture(700, SIZES["journey"]), is_published=True, created_by=people[0],
        )
        steps = [Step.objects.create(journey=journey, position=i + 1, title=title, body=body) for i, (title, body) in enumerate([
            ("Meet your buddy", "Your manager has paired you with a buddy. Grab a coffee together."),
            ("Set up your laptop", "IT will hand it over on day one. Ask in the **Technology** team if you're stuck."),
            ("Read the staff handbook", "It's in **Files** under Policies."),
            ("Say hello in the feed", "Introduce yourself with a post and a photo."),
        ])]
        assign(journey, [people[10], people[11]])  # the two new starters
        for step in steps[:2]:
            StepDone.objects.create(step=step, user=people[10])

    def jobs(self, people, today):
        vacancy = None
        for title, place, dept, kind, salary, days, contact in [
            ("Warehouse Team Leader", "Warehouse", "Operations", "full", "£32,000 a year", 21, people[3]),
            ("Junior Designer", "Manchester office", "Marketing", "part", "", 14, people[10]),
        ]:
            vacancy = Vacancy.objects.create(
                title=title, location=place, department=dept, contract_type=kind, salary=salary,
                description="A great chance to grow with us.\n\n- Friendly team\n- Training provided",
                closes_on=today + timedelta(days=days), contact=contact, created_by=people[0],
            )
        Interest.objects.create(vacancy=vacancy, user=people[8], note="I'd love to hear more about this.")

    def chat(self, people, now):
        amelia, oliver, grace = people[0], people[1], people[6]
        low, high = sorted([amelia.pk, oliver.pk])
        direct = Conversation.objects.create(pair=f"{low}:{high}", created_by=amelia)
        team = Conversation.objects.create(is_group=True, name="Summer social crew", created_by=grace)
        for conversation, members, lines in [
            (direct, [amelia, oliver], [
                (amelia, "Have you got a minute for the hub demo later?"), (oliver, "Sure, 3pm?"), (amelia, "Perfect, thanks!"),
            ]),
            (team, [grace, amelia, people[4], people[10]], [
                (grace, "Food is ordered 🍕"), (people[4], "I'll bring the speakers."),
            ]),
        ]:
            start = now - timedelta(hours=len(lines))
            for person in members:
                Membership.objects.create(conversation=conversation, user=person, joined_at=start, last_read_at=start)
            for i, (sender, text) in enumerate(lines):
                Message.objects.create(conversation=conversation, sender=sender, body=text, created_at=start + timedelta(minutes=i * 7))
            last = start + timedelta(minutes=(len(lines) - 1) * 7)
            Conversation.objects.filter(pk=conversation.pk).update(last_message_at=last)
