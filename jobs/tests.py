import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from hub import plugins, security
from hub.models import Notification, User

from . import hooks
from .models import Interest, Vacancy

FORM = {
    "title": "Night Shift Lead",
    "location": "Hull",
    "department": "Operations",
    "contract_type": "part",
    "description": "Lead the night team.",
}


def make_user(name, *perms, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)  # or the house-rules page gets in the way
    user = User.objects.create_user(name, f"{name}@example.com", "pw", first_name=name.title(), **extra)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="jobs", codename__in=perms))
    return user


class JobsTests(TestCase):
    def setUp(self):
        self.staff = make_user("sam")
        self.recruiter = make_user("rita")
        self.hr = make_user("hr", "add_vacancy", "change_vacancy", "delete_vacancy")
        self.job = self.vacancy(contact=self.recruiter)
        self.client.force_login(self.staff)

    def vacancy(self, **fields):
        fields = {
            "title": "Warehouse Operative", "location": "Leeds", "department": "Logistics",
            "description": "Pick and pack.", "created_by": self.hr, **fields,
        }
        return Vacancy.objects.create(**fields)

    def url(self, name, vacancy=None):
        return reverse(f"jobs:{name}", args=[(vacancy or self.job).pk])

    def listed(self, **params):
        return [v.title for v in self.client.get(reverse("jobs:list"), params).context["page"]]

    # --- open and closed -----------------------------------------------------------
    def test_a_vacancy_is_open_until_the_end_of_its_closing_date_or_until_an_editor_closes_it(self):
        today = timezone.localdate()
        closes_today = self.vacancy(title="Closes today", closes_on=today)
        lapsed = self.vacancy(title="Lapsed", closes_on=today - timedelta(days=1))
        shut = self.vacancy(title="Shut by HR", is_open=False)
        self.assertEqual([v.open_now for v in (self.job, closes_today, lapsed, shut)], [True, True, False, False])
        self.assertCountEqual(Vacancy.objects.open(), [self.job, closes_today])
        self.assertCountEqual(Vacancy.objects.closed(), [lapsed, shut])
        self.assertIsNotNone(shut.closed_at)

        # Ordinary staff are only ever listed the open ones...
        self.assertCountEqual(self.listed(), ["Warehouse Operative", "Closes today"])
        self.assertCountEqual(self.listed(show="closed"), ["Warehouse Operative", "Closes today"])
        self.assertNotContains(self.client.get(reverse("jobs:list")), "show=closed")
        # ...but a closed vacancy's own page still opens, and says so.
        self.assertContains(self.client.get(lapsed.get_absolute_url()), "This vacancy is closed")
        self.assertContains(self.client.get(shut.get_absolute_url()), "This vacancy is closed")
        self.assertNotContains(self.client.get(closes_today.get_absolute_url()), "This vacancy is closed")

        self.client.force_login(self.hr)
        self.assertCountEqual(self.listed(show="closed"), ["Lapsed", "Shut by HR"])

    # --- the list ------------------------------------------------------------------
    def test_list_search_and_filters(self):
        self.vacancy(title="Accounts Assistant", location="York", department="Finance")
        self.vacancy(title="Driver", location="York", department="Logistics", closes_on=timezone.localdate())
        self.vacancy(title="Old York job", location="York", department="Archive", is_open=False)
        self.assertCountEqual(self.listed(q="york"), ["Accounts Assistant", "Driver"])
        self.assertEqual(self.listed(q="FINANCE"), ["Accounts Assistant"])
        self.assertEqual(self.listed(q="warehouse leeds"), ["Warehouse Operative"])
        self.assertCountEqual(self.listed(department="Logistics"), ["Driver", "Warehouse Operative"])
        self.assertEqual(self.listed(location="York", department="Logistics"), ["Driver"])
        self.assertEqual(self.listed(q="driver", location="Leeds"), [])

        Interest.objects.create(vacancy=self.job, user=self.staff)
        response = self.client.get(reverse("jobs:list"))
        # The filters offer only values used by vacancies in the list.
        self.assertEqual(list(response.context["locations"]), ["Leeds", "York"])
        self.assertEqual(list(response.context["departments"]), ["Finance", "Logistics"])
        self.assertContains(response, "Leeds · Logistics · Full-time")
        self.assertContains(response, "You're interested", count=1)
        self.assertContains(response, '<span class="pill orange">Closes ', count=1)
        self.assertContains(self.client.get(reverse("jobs:list"), {"q": "zzz"}), "No vacancies match")
        Vacancy.objects.all().delete()
        self.assertContains(self.client.get(reverse("jobs:list")), "No open vacancies right now")

    def test_the_description_is_formatted_and_never_trusted(self):
        job = self.vacancy(description="**Great** team <script>alert(1)</script>")
        response = self.client.get(job.get_absolute_url())
        self.assertContains(response, "<strong>Great</strong> team &lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)")

    # --- interest ------------------------------------------------------------------
    def test_interest_is_recorded_and_the_recruiter_is_told_once(self):
        response = self.client.post(self.url("interest"), {"note": "I have a forklift licence"})
        self.assertRedirects(response, self.job.get_absolute_url())
        interest = Interest.objects.get()
        self.assertEqual((interest.vacancy, interest.user, interest.note), (self.job, self.staff, "I have a forklift licence"))
        alert = Notification.objects.get()  # one, and not to the person who added the vacancy
        self.assertEqual((alert.recipient, alert.actor, alert.category), (self.recruiter, self.staff, "general"))
        self.assertEqual((alert.message, alert.url), ("Sam is interested in Warehouse Operative", self.url("interested")))

        self.client.post(self.url("interest"), {"note": "Again"})  # a double click changes nothing
        self.assertEqual((Interest.objects.get().note, Notification.objects.count()), ("I have a forklift licence", 1))
        # People always see their own interest on the vacancy's page.
        response = self.client.get(self.job.get_absolute_url())
        self.assertContains(response, "I have a forklift licence")
        self.assertContains(response, self.url("withdraw"))
        self.assertNotContains(response, self.url("interest") + '"')

        no_recruiter = self.vacancy(title="Driver")  # then whoever added the vacancy is told
        self.client.post(self.url("interest", no_recruiter), {"note": "x" * 2000})
        self.assertEqual(Notification.objects.get(url=self.url("interested", no_recruiter)).recipient, self.hr)
        self.assertEqual(len(no_recruiter.interests.get().note), 1000)

    def test_interest_skips_a_recruiter_who_has_left(self):
        User.objects.filter(pk=self.recruiter.pk).update(is_active=False)
        self.client.post(self.url("interest"))
        self.assertEqual(Notification.objects.get().recipient, self.hr)  # whoever added the vacancy instead
        User.objects.filter(pk=self.hr.pk).update(is_active=False)
        response = self.client.post(self.url("interest", self.vacancy(title="Driver", contact=self.recruiter)), follow=True)
        self.assertEqual(Notification.objects.count(), 1)  # nobody is left to tell, and the page doesn't pretend
        self.assertContains(response, "HR can see you")

    def test_no_interest_in_a_closed_vacancy(self):
        today = timezone.localdate()
        for closed in (self.vacancy(is_open=False), self.vacancy(closes_on=today - timedelta(days=1))):
            response = self.client.post(self.url("interest", closed), follow=True)
            self.assertContains(response, "This vacancy is closed")
            self.assertNotContains(response, "I'm interested")
        self.assertFalse(Interest.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.client.post(self.url("interest", self.vacancy(closes_on=today)))  # the last day still counts
        self.assertEqual(Interest.objects.count(), 1)

    def test_withdrawing_removes_the_interest_and_coming_back_does_not_flood_the_recruiter(self):
        self.client.post(self.url("interest"), {"note": "Keen"})
        self.assertEqual(self.client.get(self.url("withdraw")).status_code, 405)  # writes are POST only
        self.assertEqual(self.client.get(self.url("interest")).status_code, 405)
        self.client.post(self.url("withdraw"))
        self.assertFalse(Interest.objects.exists())
        self.assertNotContains(self.client.get(self.job.get_absolute_url()), "Keen")
        self.client.post(self.url("interest"))
        self.assertEqual(Notification.objects.count(), 1)  # the first alert is still unread
        # Withdrawing still works after the vacancy has closed.
        Vacancy.objects.update(is_open=False)
        self.client.post(self.url("withdraw"))
        self.assertFalse(Interest.objects.exists())

    def test_one_person_can_show_interest_in_20_vacancies_a_day(self):
        self.assertEqual(security.LIMITS["interest"], (20, timedelta(days=1)))
        for n in range(20):
            Interest.objects.create(vacancy=self.vacancy(title=f"Job {n}"), user=self.staff)
        with self.assertLogs("hub.security", "WARNING") as logs:
            response = self.client.post(self.url("interest"), follow=True)
        self.assertContains(response, "Please try again later.")
        self.assertEqual((logs.records[0].getMessage(), logs.records[0].details["limit"]), ("rate_limited", "interest"))
        self.assertFalse(self.job.interests.exists())
        Interest.objects.update(created_at=timezone.now() - timedelta(days=1, minutes=1))
        self.client.post(self.url("interest"))
        self.assertTrue(self.job.interests.exists())

    def test_who_is_interested_is_private(self):
        Interest.objects.create(vacancy=self.job, user=self.staff, note="Keen as mustard")
        colleague = make_user("colin")
        for person in (self.staff, colleague):  # not even someone who is interested themselves
            self.client.force_login(person)
            self.assertEqual(self.client.get(self.url("interested")).status_code, 404)
            self.assertNotContains(self.client.get(self.job.get_absolute_url()), self.url("interested"))
        self.assertNotContains(self.client.get(self.job.get_absolute_url()), "Keen as mustard")

        added_by_colin = self.vacancy(title="Driver", created_by=colleague)
        self.assertEqual(self.client.get(self.url("interested", added_by_colin)).status_code, 200)  # its creator
        for person in (self.recruiter, self.hr):  # its recruiter, and editors
            self.client.force_login(person)
            response = self.client.get(self.url("interested"))
            self.assertContains(response, "Keen as mustard")
            self.assertContains(response, self.staff.get_absolute_url())
            self.assertContains(self.client.get(self.job.get_absolute_url()), "1 colleague is interested")
        self.assertEqual(self.client.get(self.url("interested", added_by_colin)).status_code, 200)
        self.client.force_login(self.recruiter)  # a recruiter only sees their own vacancies' lists
        self.assertEqual(self.client.get(self.url("interested", added_by_colin)).status_code, 404)

    def test_the_interested_list_links_to_chat_once_chat_has_its_with_page(self):
        try:
            chat_url = reverse("chat:with", args=[self.staff.pk])
        except NoReverseMatch:
            self.skipTest("chat:with is not there yet")
        Interest.objects.create(vacancy=self.job, user=self.staff)
        self.client.force_login(self.recruiter)
        self.assertContains(self.client.get(self.url("interested")), f'href="{chat_url}"')

    # --- editors -------------------------------------------------------------------
    def test_editor_views_need_their_permission(self):
        views = [("get", reverse("jobs:new")), ("post", reverse("jobs:new")), ("get", self.url("edit")),
                 ("post", self.url("edit")), ("post", self.url("toggle")), ("post", self.url("delete"))]
        for method, url in views:
            self.assertEqual(getattr(self.client, method)(url, FORM).status_code, 403, url)
        self.assertEqual(list(Vacancy.objects.values_list("title", "is_open")), [("Warehouse Operative", True)])
        response = self.client.get(self.job.get_absolute_url())
        for name in ("edit", "toggle", "delete"):
            self.assertNotContains(response, self.url(name))
        self.assertNotContains(self.client.get(reverse("jobs:list")), reverse("jobs:new"))

        # The three permissions are separate: being able to change is not being able to add or delete.
        self.client.force_login(make_user("changer", "change_vacancy"))
        self.assertEqual(self.client.get(reverse("jobs:new")).status_code, 403)
        self.assertEqual(self.client.post(self.url("delete")).status_code, 403)
        self.assertEqual(self.client.get(self.url("edit")).status_code, 200)
        response = self.client.get(self.job.get_absolute_url())
        self.assertContains(response, self.url("toggle"))
        self.assertNotContains(response, self.url("delete"))
        self.client.force_login(make_user("adder", "add_vacancy"))
        self.assertEqual(self.client.get(self.url("edit")).status_code, 403)
        self.assertEqual(self.client.post(self.url("toggle")).status_code, 403)

        self.client.logout()
        self.assertRedirects(self.client.get(reverse("jobs:list")), reverse("login") + "?next=/jobs/", fetch_redirect_response=False)

    def test_editors_publish_edit_close_reopen_and_delete_and_each_is_logged(self):
        self.client.force_login(self.hr)
        with self.assertLogs("hub.security", "INFO") as logs:
            response = self.client.post(reverse("jobs:new"), {**FORM, "contact": self.recruiter.pk})
            job = Vacancy.objects.get(title="Night Shift Lead")
            self.assertRedirects(response, job.get_absolute_url())
            self.assertEqual((job.created_by, job.contact, job.open_now), (self.hr, self.recruiter, True))

            self.client.post(self.url("edit", job), {**FORM, "salary": "£30,000 a year"})
            job.refresh_from_db()
            self.assertEqual((job.salary, job.contact, job.created_by), ("£30,000 a year", None, self.hr))

            self.client.post(self.url("toggle", job), {"open": "0"})
            job.refresh_from_db()
            self.assertFalse(job.is_open)
            self.assertIsNotNone(job.closed_at)
            self.assertContains(self.client.get(job.get_absolute_url()), "Reopen")
            # A second "Close" (a double-click, or a colleague's older copy of the page) must not reopen it.
            self.client.post(self.url("toggle", job), {"open": "0"})
            job.refresh_from_db()
            self.assertFalse(job.is_open)

            self.client.post(self.url("toggle", job), {"open": "1"})
            job.refresh_from_db()
            self.assertEqual((job.is_open, job.closed_at), (True, None))

            Interest.objects.create(vacancy=job, user=self.staff)
            self.assertRedirects(self.client.post(self.url("delete", job)), reverse("jobs:list"))
            self.assertFalse(Vacancy.objects.filter(pk=job.pk).exists())
            self.assertFalse(Interest.objects.exists())
        events = [(r.getMessage(), r.details["vacancy_id"], r.details["user"]) for r in logs.records]
        expected = ["vacancy_published", "vacancy_closed", "vacancy_published", "vacancy_deleted"]
        self.assertEqual(events, [(event, job.pk, "hr@example.com") for event in expected])

    def test_reopening_a_vacancy_past_its_closing_date_clears_the_date(self):
        lapsed = self.vacancy(closes_on=timezone.localdate() - timedelta(days=3))
        self.client.force_login(self.hr)
        with self.assertLogs("hub.security", "INFO"):
            self.client.post(self.url("toggle", lapsed), {"open": "1"})
        lapsed.refresh_from_db()
        self.assertEqual((lapsed.open_now, lapsed.closes_on), (True, None))

    def test_the_form_refuses_unsafe_links_and_new_closing_dates_in_the_past(self):
        self.client.force_login(self.hr)
        for bad in ("javascript:alert(1)", "JaVaScript:alert(1)", "data:text/html,hello", "ftp://example.com/job", "careers"):
            response = self.client.post(reverse("jobs:new"), {**FORM, "apply_url": bad})
            self.assertTrue(response.context["form"].errors["apply_url"], bad)
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(reverse("jobs:new"), {**FORM, "closes_on": yesterday})
        self.assertContains(response, "The closing date is in the past.")
        self.assertFalse(Vacancy.objects.filter(title="Night Shift Lead").exists())

        with self.assertLogs("hub.security", "INFO"):
            self.client.post(reverse("jobs:new"), {**FORM, "apply_url": "https://careers.example.com/jobs/1?ref=hub"})
        job = Vacancy.objects.get(title="Night Shift Lead")
        self.assertContains(
            self.client.get(job.get_absolute_url()),
            '<a href="https://careers.example.com/jobs/1?ref=hub" target="_blank" rel="noopener noreferrer">',
        )
        # A vacancy that has since closed can still have a typo fixed without touching its date.
        Vacancy.objects.filter(pk=job.pk).update(closes_on=yesterday)
        self.client.post(self.url("edit", job), {**FORM, "title": "Night Shift Leader", "closes_on": yesterday})
        self.assertTrue(Vacancy.objects.filter(title="Night Shift Leader").exists())

    # --- hooks ---------------------------------------------------------------------
    def test_menu_search_and_export_hooks(self):
        self.assertIn((20, "Jobs", "jobs:list", "briefcase"), plugins.MENU)
        self.assertIn(hooks.search, plugins.SEARCH_PROVIDERS)
        self.assertIn(hooks.export, plugins.EXPORTERS)
        self.assertIn(hooks.purge, plugins.PURGERS)

        self.vacancy(title="Warehouse Manager", is_open=False)  # search is over open vacancies only
        self.vacancy(title="Warehouse Cleaner", location="York")
        self.assertEqual(
            hooks.search(self.staff, "warehouse leeds", 5),
            ("Jobs", [("Warehouse Operative", self.job.get_absolute_url(), "Leeds · Logistics")]),
        )
        self.assertEqual(len(hooks.search(self.staff, "warehouse", 1)[1]), 1)

        Interest.objects.create(vacancy=self.job, user=self.staff, note="Keen")
        Interest.objects.create(vacancy=self.job, user=self.recruiter, note="Someone else's")
        key, data, files = hooks.export(self.staff)
        self.assertEqual((key, files), ("jobs", []))
        self.assertEqual([(row["vacancy__title"], row["note"]) for row in data], [("Warehouse Operative", "Keen")])
        self.assertIn(str(timezone.now().year), json.dumps(data, default=str))  # how hub writes my-data.json
        self.assertEqual(hooks.export(self.hr)[1], [])

    def test_purger_forgets_interest_180_days_after_a_vacancy_closed(self):
        now = timezone.now()
        today = timezone.localdate(now)

        def interest_in(title, closed_at=None, **fields):
            job = self.vacancy(title=title, **fields)
            Vacancy.objects.filter(pk=job.pk, is_open=False).update(closed_at=closed_at)
            Interest.objects.create(vacancy=job, user=self.staff)

        interest_in("Still open")
        interest_in("Closing date far ahead", closes_on=today + timedelta(days=30))
        interest_in("Closed last week", is_open=False, closed_at=now - timedelta(days=7))
        interest_in("Closed 179 days ago", is_open=False, closed_at=now - timedelta(days=179))
        interest_in("Closed 181 days ago", is_open=False, closed_at=now - timedelta(days=181))
        interest_in("Lapsed 180 days ago", closes_on=today - timedelta(days=180))
        interest_in("Lapsed 181 days ago", closes_on=today - timedelta(days=181))
        self.assertEqual(hooks.purge(now), ("old job interests", 2))
        self.assertCountEqual(
            Interest.objects.values_list("vacancy__title", flat=True),
            ["Still open", "Closing date far ahead", "Closed last week", "Closed 179 days ago", "Lapsed 180 days ago"],
        )
        self.assertEqual(Vacancy.objects.count(), 8)  # the vacancies themselves stay
        self.assertEqual(hooks.purge(now), ("old job interests", 0))
