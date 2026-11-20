import json
import os
import shutil
import tempfile
from io import BytesIO

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from hub import plugins
from hub.models import Community, Notification, User

from . import views
from .models import Assignment, Journey, Step, StepDone, ensure_assignments

TEMP_MEDIA = tempfile.mkdtemp()


def make_user(name, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)  # or the house rules page gets in the way
    return User.objects.create_user(name, f"{name}@example.com", "pw", first_name=name.title(), **extra)


def picture():
    buffer = BytesIO()
    Image.new("RGB", (40, 40), "blue").save(buffer, "PNG")
    return SimpleUploadedFile("cover.png", buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class JourneyTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.editor = make_user("editor")
        self.editor.user_permissions.add(*Permission.objects.filter(content_type__app_label="journeys"))
        self.team = Community.objects.create(name="Warehouse", slug="warehouse", kind=Community.UNIT)
        self.team.members.add(self.alice)
        self.client.force_login(self.alice)

    def journey(self, title="Welcome", steps=2, published=True, audience=None):
        journey = Journey.objects.create(title=title, is_published=published, created_by=self.editor)
        if audience:
            journey.audiences.add(audience)
        for number in range(1, steps + 1):
            Step.objects.create(journey=journey, position=number, title=f"Step {number}", body="Read **this**.")
        return journey

    def url(self, name, journey, step=None):
        return reverse(f"journeys:{name}", args=[journey.pk] + ([step.pk] if step else []))

    def finish(self, journey, user):
        Assignment.objects.get_or_create(journey=journey, user=user)
        self.client.force_login(user)
        for step in journey.steps.all():
            response = self.client.post(self.url("step_done", journey, step), follow=True)
        return response

    # --- who gets a journey ---------------------------------------------------------
    def test_a_journey_reaches_everyone_or_only_its_groups_and_only_when_published(self):
        for_all = self.journey("For all")
        for_team = self.journey("For the warehouse", audience=self.team)
        self.journey("Draft", published=False)
        self.assertEqual(set(Journey.objects.reaching(self.alice)), {for_all, for_team})
        self.assertEqual(set(Journey.objects.reaching(self.bob)), {for_all})

    def test_opening_the_list_assigns_and_tells_the_person_once(self):
        journey = self.journey()
        self.client.get(reverse("journeys:list"))
        self.client.get(reverse("journeys:list"))
        ensure_assignments(self.alice)
        self.assertEqual(Assignment.objects.filter(journey=journey, user=self.alice).count(), 1)
        alert = Notification.objects.get(recipient=self.alice)
        self.assertEqual(alert.message, "New journey for you: Welcome")
        self.assertEqual((alert.category, alert.url, alert.actor), ("journeys", journey.get_absolute_url(), self.editor))

    def test_publishing_assigns_everyone_it_reaches_who_is_active_and_tells_them_once(self):
        make_user("leaver", is_active=False)
        journey = self.journey(published=False)
        self.client.force_login(self.editor)
        self.client.post(self.url("publish", journey), {"publish": "1"})
        self.assertEqual(
            set(journey.assignments.values_list("user__username", flat=True)), {"alice", "bob", "editor"}
        )
        self.client.post(self.url("publish", journey), {"publish": "1"})  # a double-click keeps it published
        self.assertTrue(Journey.objects.get(pk=journey.pk).is_published)
        self.client.post(self.url("publish", journey), {"publish": "0"})  # unpublish
        self.assertFalse(Journey.objects.get(pk=journey.pk).is_published)
        self.client.post(self.url("publish", journey), {"publish": "1"})  # and publish again
        self.assertEqual(Notification.objects.filter(recipient=self.bob, category="journeys").count(), 1)
        self.assertEqual(journey.assignments.count(), 3)

    def test_people_who_join_the_team_or_the_company_later_get_its_journeys_straight_away(self):
        for_team = self.journey("Warehouse safety", audience=self.team)
        for_everyone = self.journey("Welcome")
        self.team.members.add(self.bob)  # Bob moves to the warehouse
        self.assertTrue(for_team.assignments.filter(user=self.bob).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.bob, message__contains="Warehouse safety").exists())

        starter = make_user("starter")  # e.g. a first sign-in
        self.assertEqual(list(Assignment.objects.filter(user=starter).values_list("journey", flat=True)), [for_everyone.pk])
        make_user("leaver", is_active=False).communities.add(self.team)
        self.assertFalse(Assignment.objects.filter(user__username="leaver").exists())

    def test_a_journey_without_steps_cannot_be_published(self):
        journey = self.journey(steps=0, published=False)
        self.client.force_login(self.editor)
        self.client.post(self.url("publish", journey), {"publish": "1"})
        self.assertFalse(Journey.objects.get(pk=journey.pk).is_published)

    # --- who may open what ----------------------------------------------------------
    def test_people_without_the_journey_get_404(self):
        journey = self.journey(audience=self.team)
        step = journey.steps.first()
        self.client.force_login(self.bob)
        self.client.get(reverse("journeys:list"))
        self.assertEqual(self.client.get(self.url("detail", journey)).status_code, 404)
        self.assertEqual(self.client.get(self.url("step", journey, step)).status_code, 404)
        self.assertEqual(self.client.post(self.url("step_done", journey, step)).status_code, 404)
        self.assertFalse(StepDone.objects.exists())
        self.client.force_login(self.alice)
        self.client.get(reverse("journeys:list"))
        self.assertEqual(self.client.get(self.url("detail", journey)).status_code, 200)

    def test_unpublished_journeys_are_for_editors_only(self):
        journey = self.journey()
        self.client.get(reverse("journeys:list"))  # alice gets it while it is published
        Journey.objects.update(is_published=False)
        self.assertEqual(self.client.get(self.url("detail", journey)).status_code, 404)
        self.assertNotContains(self.client.get(reverse("journeys:list")), "Welcome")
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(self.url("detail", journey)).status_code, 200)
        self.assertContains(self.client.get(reverse("journeys:list")), "Draft")

    # --- working through the steps ---------------------------------------------------
    def test_steps_unlock_in_order_but_editors_can_open_any(self):
        journey = self.journey(steps=3)
        first, second, _third = journey.steps.all()
        self.client.get(reverse("journeys:list"))
        self.assertRedirects(self.client.get(self.url("step", journey, second)), journey.get_absolute_url())
        self.client.post(self.url("step_done", journey, second))
        self.assertFalse(StepDone.objects.exists())
        self.assertContains(self.client.get(self.url("detail", journey)), "Locked")
        response = self.client.post(self.url("step_done", journey, first))
        self.assertRedirects(response, self.url("step", journey, second))
        self.assertContains(self.client.get(self.url("step", journey, second)), "Mark as done and continue")
        self.client.force_login(self.editor)
        response = self.client.get(self.url("step", journey, second))
        self.assertContains(response, "Preview only")
        self.assertContains(response, "Read <strong>this</strong>.")

    def test_finishing_the_last_step_records_completion_once(self):
        journey = self.journey()
        response = self.finish(journey, self.alice)
        self.assertRedirects(response, journey.get_absolute_url())
        self.assertContains(response, "You have finished")
        finished_at = Assignment.objects.get(user=self.alice).completed_at
        self.assertIsNotNone(finished_at)
        response = self.finish(journey, self.alice)
        self.assertNotContains(response, "You have finished")
        self.assertEqual(Assignment.objects.get(user=self.alice).completed_at, finished_at)
        self.assertEqual(StepDone.objects.filter(user=self.alice).count(), 2)

    def test_deleting_the_only_step_someone_had_left_finishes_their_journey(self):
        journey = self.journey()
        first, second = journey.steps.all()
        self.client.get(reverse("journeys:list"))
        self.client.post(self.url("step_done", journey, first))
        Assignment.objects.create(journey=journey, user=self.bob)  # has done nothing
        self.client.force_login(self.editor)
        self.client.post(self.url("step_delete", journey, second))
        self.assertIsNotNone(Assignment.objects.get(user=self.alice).completed_at)
        self.assertIsNone(Assignment.objects.get(user=self.bob).completed_at)

    def test_a_new_step_means_nobody_has_finished_until_they_do_it(self):
        journey = self.journey("Fire safety")
        self.finish(journey, self.alice)
        self.client.force_login(self.editor)
        self.client.post(self.url("step_new", journey), {"title": "New assembly point", "body": "Read this", "position": 3})
        self.assertIsNone(Assignment.objects.get(user=self.alice).completed_at)
        self.client.force_login(self.alice)
        self.client.post(self.url("step_done", journey, journey.steps.get(title="New assembly point")))
        self.assertIsNotNone(Assignment.objects.get(user=self.alice).completed_at)

    def test_list_filters_and_card_buttons(self):
        done = self.journey("Fire safety")
        started = self.journey("Welcome pack")
        self.journey("Fresh one")
        self.client.get(reverse("journeys:list"))
        self.finish(done, self.alice)
        self.client.post(self.url("step_done", started, started.steps.first()))

        def titles(show):
            response = self.client.get(reverse("journeys:list"), {"show": show})
            return {a.journey.title for a in response.context["assignments"]}

        self.assertEqual(titles("all"), {"Fire safety", "Welcome pack", "Fresh one"})
        self.assertEqual(titles("incomplete"), {"Welcome pack", "Fresh one"})
        self.assertEqual(titles("completed"), {"Fire safety"})
        page = self.client.get(reverse("journeys:list"))
        for text in ["Review", "Continue", "Start", "1 of 2 steps", "2 of 2 steps", "0 of 2 steps"]:
            self.assertContains(page, text)
        self.assertNotContains(page, "New journey")
        self.assertContains(self.client.get(reverse("journeys:list"), {"show": "completed"}), "Fire safety")

    # --- editors --------------------------------------------------------------------
    def test_editor_pages_are_for_editors_only(self):
        journey = self.journey()
        step = journey.steps.first()
        pages = [
            ("get", reverse("journeys:new")),
            ("get", self.url("edit", journey)),
            ("get", self.url("progress", journey)),
            ("get", self.url("step_new", journey)),
            ("get", self.url("step_edit", journey, step)),
            ("post", self.url("publish", journey)),
            ("post", self.url("step_delete", journey, step)),
            ("post", self.url("delete", journey)),
        ]
        for method, url in pages:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse("journeys:new"), {"title": "Sneaky"}).status_code, 403)
        self.assertTrue(Journey.objects.filter(pk=journey.pk, is_published=True, steps=step).exists())
        self.client.force_login(self.editor)
        for method, url in pages:
            self.assertIn(getattr(self.client, method)(url).status_code, (200, 302), url)
        self.assertFalse(Journey.objects.exists())

    def test_editors_create_a_journey_with_a_cover_and_steps(self):
        self.client.force_login(self.editor)
        Community.objects.create(name="Secret club", slug="secret-club", is_private=True)
        form = self.client.get(reverse("journeys:new"))
        self.assertContains(form, "Warehouse")
        self.assertNotContains(form, "Secret club")  # private groups stay private from editors who aren't in them
        data = {"title": "Safety refresher", "description": "Once a year.", "audiences": [self.team.pk]}
        self.client.post(reverse("journeys:new"), {**data, "cover": picture()})
        journey = Journey.objects.get()
        self.assertEqual((journey.created_by, journey.is_published), (self.editor, False))
        self.assertEqual(list(journey.audiences.all()), [self.team])
        self.assertTrue(journey.cover.name.startswith("journeys/"))
        not_a_picture = SimpleUploadedFile("cover.png", b"hello", content_type="image/png")
        response = self.client.post(self.url("edit", journey), {**data, "cover": not_a_picture})
        self.assertEqual(response.status_code, 200)  # the form comes back with an error
        first_cover = journey.cover.path
        self.client.post(self.url("edit", journey), {**data, "cover": picture()})
        self.assertFalse(os.path.exists(first_cover))  # a replaced cover is removed from disk
        self.assertTrue(os.path.exists(Journey.objects.get().cover.path))
        self.client.post(self.url("step_new", journey), {"title": "Read the rules", "body": "Please.", "position": 1})
        self.assertEqual(journey.steps.get().title, "Read the rules")
        self.assertContains(self.client.get(self.url("detail", journey)), "Read the rules")

    def test_step_links_must_be_web_addresses(self):
        journey = self.journey(steps=0)
        self.client.force_login(self.editor)
        for bad in ["javascript:alert(1)", "ftp://example.com/file"]:
            response = self.client.post(
                self.url("step_new", journey), {"title": "Bad", "body": "x", "position": 1, "link_url": bad}
            )
            self.assertEqual(response.status_code, 200, bad)
            with self.assertRaises(ValidationError):
                Step(journey=journey, title="Bad", link_url=bad).full_clean()
        self.assertFalse(journey.steps.exists())
        good = {"title": "Good", "body": "x", "position": 1, "link_url": "https://example.com/handbook"}
        self.client.post(self.url("step_new", journey), good)
        Assignment.objects.create(journey=journey, user=self.editor)
        response = self.client.get(self.url("step", journey, journey.steps.get()))
        self.assertContains(response, 'href="https://example.com/handbook"')

    def test_progress_page_counts_people_and_shows_each_status(self):
        journey = self.journey()
        self.finish(journey, self.alice)
        self.client.force_login(self.bob)
        self.client.get(reverse("journeys:list"))
        self.client.post(self.url("step_done", journey, journey.steps.first()))
        make_user("carol")  # a new joiner gets the journey (it is for everyone) without opening it
        self.client.force_login(self.editor)
        response = self.client.get(self.url("progress", journey))
        self.assertEqual((response.context["assigned"], response.context["finished"]), (3, 1))
        for text in ["Finished on", "1 of 2", "Not started"]:
            self.assertContains(response, text)

    # --- hooks ----------------------------------------------------------------------
    def test_menu_search_and_export_hooks(self):
        self.assertIn((40, "Journeys", "journeys:list", "map"), plugins.MENU)
        self.assertIn(views.search, plugins.SEARCH_PROVIDERS)
        self.assertIn(views.export, plugins.EXPORTERS)
        journey = self.journey("Fire safety")
        self.journey("Fire wardens", audience=Community.objects.create(name="Wardens", slug="wardens"))
        self.finish(journey, self.alice)
        label, results = views.search(self.alice, "fire", 5)
        self.assertEqual((label, results), ("Journeys", [("Fire safety", journey.get_absolute_url(), "Completed")]))
        self.assertEqual(views.search(self.bob, "fire", 5), ("Journeys", []))
        self.assertEqual(views.search(self.alice, "safety fire", 5)[1][0][0], "Fire safety")  # every word, any order
        key, rows, files = views.export(self.alice)
        self.assertEqual((key, files, len(rows)), ("journeys", [], 1))
        self.assertEqual(rows[0]["title"], "Fire safety")
        self.assertIsNotNone(rows[0]["assigned_at"])
        self.assertIsNotNone(rows[0]["completed_at"])
        self.assertEqual([tick["step"] for tick in rows[0]["steps_done"]], ["Step 1", "Step 2"])
        json.dumps(rows, default=str)  # the way "Download my data" writes it

    def test_covers_of_drafts_are_served_to_editors_only(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("journeys:new"), {"title": "Draft", "cover": picture()})
        journey = Journey.objects.get()
        cover = reverse("media", args=[journey.cover.name])
        self.assertIs(plugins.MEDIA_GUARDS["journeys"], views.guard_cover)
        self.assertEqual(self.client.get(cover).status_code, 200)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(cover).status_code, 404)
        self.assertFalse(views.guard_cover(self.alice, "journeys/unknown.jpg"))
        Journey.objects.update(is_published=True)
        self.assertEqual(self.client.get(cover).status_code, 200)
