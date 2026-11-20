import os
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from hub import plugins
from hub.models import Community, User
from hub.security import LIMITS

from . import hooks
from .files import MAX_MB, check_document
from .models import Article, Category, Document, FeaturedLink, Folder

TEMP_MEDIA = tempfile.mkdtemp()
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 24
ZIP = b"PK\x03\x04" + b"\0" * 26
PROGRAM = b"MZ\x90\x00\x03\x00\x00\x00"  # how a Windows .exe starts
WEB_PAGE = b"<html><script>alert(1)</script></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def picture(fmt):
    out = BytesIO()
    Image.new("RGB", (4, 4), "red").save(out, fmt)
    return out.getvalue()


SAMPLES = {
    "a.pdf": b"%PDF-1.7\n%%EOF",
    "a.docx": ZIP, "a.xlsx": ZIP, "a.pptx": ZIP,
    "a.doc": OLE, "a.xls": OLE, "a.ppt": OLE,
    "a.txt": "Café opening hours".encode(),
    "a.csv": b"name,team\nAlice,Sales\n",
    "a.png": picture("PNG"), "a.jpg": picture("JPEG"), "a.JPEG": picture("JPEG"),
    "a.gif": picture("GIF"), "a.webp": picture("WEBP"),
    "a.mp4": b"\x00\x00\x00\x18ftypmp42" + b"\0" * 12,
}


def upload(name, content=None):
    return SimpleUploadedFile(name, SAMPLES["a.pdf"] if content is None else content)


def make_user(name, *permissions, **extra):
    extra.setdefault("policy_version", settings.POLICY_VERSION)
    user = User.objects.create_user(name, f"{name}@example.com", "pw", first_name=name.title(), **extra)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="library", codename__in=permissions))
    return user


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class LibraryTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = make_user("alice")  # an ordinary colleague
        self.librarian = make_user(
            "librarian", "add_document", "delete_document", "add_folder", "delete_folder", "add_featuredlink",
            "add_article", "change_article", "delete_article",
        )
        self.bob = make_user("bob")  # admin of the private group
        self.carol = make_user("carol")  # member of the private group
        self.secret = Community.objects.create(name="Pay Review", slug="pay-review", is_private=True)
        self.secret.members.add(self.bob, self.carol)
        self.secret.admins.add(self.bob)
        self.client.force_login(self.alice)

    def send(self, user, url_name, *args, **data):
        self.client.force_login(user)
        return self.client.post(reverse(f"library:{url_name}", args=args), data)

    def document(self, community=None, name="Staff handbook.pdf", **extra):
        extra.setdefault("uploaded_by", self.librarian)
        extra.setdefault("title", os.path.splitext(name)[0])
        file = check_document(upload(name))
        return Document.objects.create(
            community=community, file=file, original_name=name, size=file.size, **extra
        )

    def download(self, user, url):
        """(status, Content-Disposition). Reads the file to the end, so it is closed again."""
        self.client.force_login(user)
        response = self.client.get(url)
        if response.status_code == 200:
            b"".join(response.streaming_content)
        return response.status_code, response.get("Content-Disposition", "")

    # --- checking uploads ----------------------------------------------------------
    def test_each_allowed_type_is_accepted_and_stored_under_a_random_name(self):
        for name, content in SAMPLES.items():
            checked = check_document(upload(name, content))
            self.assertRegex(checked.name, r"^[0-9a-f]{32}\.[a-z0-9]+$", name)
            self.assertTrue(checked.name.endswith(os.path.splitext(name)[1].lower()), name)
            self.assertEqual(checked.read(), content, name)

    def test_disguised_wrong_and_oversized_files_are_refused(self):
        refused = [
            ("setup.exe", PROGRAM), ("page.html", WEB_PAGE), ("logo.svg", SVG), ("notes", b"no ending"),
            # Renamed to look like an allowed type:
            ("setup.pdf", PROGRAM), ("setup.docx", PROGRAM), ("setup.doc", PROGRAM), ("setup.txt", PROGRAM),
            ("setup.png", PROGRAM), ("setup.mp4", PROGRAM),
            ("page.pdf", WEB_PAGE), ("page.xlsx", WEB_PAGE), ("page.jpg", WEB_PAGE), ("page.gif", WEB_PAGE),
            ("logo.png", SVG), ("logo.webp", SVG), ("logo.pdf", SVG),
            ("photo.png", SAMPLES["a.jpg"]),  # a real picture, but not the type its name says
            ("latin1.csv", "Café".encode("latin-1")), ("empty.txt", b""),
        ]
        for name, content in refused:
            with self.assertRaises(ValidationError, msg=name):
                check_document(upload(name, content))
        too_big = upload("big.pdf")
        too_big.size = MAX_MB * 1024 * 1024 + 1
        with self.assertRaisesMessage(ValidationError, "Files must be under 50 MB."):
            check_document(too_big)

    def test_uploads_pause_when_the_disk_is_nearly_full(self):
        with mock.patch("hub.media.disk_free_share", return_value=0.01), self.assertRaises(ValidationError):
            check_document(upload("a.pdf"))

    # --- files ---------------------------------------------------------------------
    def test_company_files_need_the_permission_and_group_files_a_group_admin(self):
        def file():
            return {"file": upload("Staff handbook.pdf")}

        self.assertEqual(self.send(self.alice, "upload", **file()).status_code, 403)
        self.assertEqual(self.send(self.bob, "upload", **file()).status_code, 403)  # a group admin, but not for company files
        self.assertEqual(self.send(self.carol, "upload", community="pay-review", **file()).status_code, 403)  # member only
        self.assertEqual(self.send(self.alice, "upload", community="pay-review", **file()).status_code, 404)  # can't see it
        self.assertFalse(Document.objects.exists())

        self.assertRedirects(self.send(self.librarian, "upload", **file()), reverse("library:files"))
        self.assertRedirects(
            self.send(self.bob, "upload", community="pay-review", title="Bands", **file()),
            reverse("library:group_files", args=["pay-review"]),
        )
        company, group = Document.objects.order_by("pk")
        self.assertEqual((company.community, company.title, company.original_name), (None, "Staff handbook", "Staff handbook.pdf"))
        self.assertEqual((company.size, company.uploaded_by), (len(SAMPLES["a.pdf"]), self.librarian))
        self.assertRegex(company.file.name, r"^library/\d{4}/\d{2}/[0-9a-f]{32}\.pdf$")
        self.assertEqual((group.community, group.title, group.uploaded_by), (self.secret, "Bands", self.bob))

        # Deleting follows the same rule.
        self.assertEqual(self.send(self.carol, "document_delete", group.pk).status_code, 403)
        self.assertEqual(self.send(self.alice, "document_delete", group.pk).status_code, 404)
        self.assertEqual(self.send(self.bob, "document_delete", company.pk).status_code, 403)
        self.assertEqual(self.send(self.bob, "document_delete", group.pk).status_code, 302)
        self.assertEqual(self.send(self.librarian, "document_delete", company.pk).status_code, 302)
        self.assertFalse(Document.objects.exists())

    def test_a_disguised_upload_is_refused_with_a_message_and_nothing_is_stored(self):
        self.client.force_login(self.librarian)
        response = self.client.post(reverse("library:upload"), {"file": upload("setup.pdf", PROGRAM)}, follow=True)
        self.assertContains(response, "look like a real PDF file")
        self.assertFalse(Document.objects.exists())
        self.assertEqual(self.client.get(reverse("library:upload")).status_code, 405)  # writes are POST only

    def test_uploads_are_limited_per_day(self):
        self.assertEqual(LIMITS["document"], (50, timedelta(days=1)))
        with mock.patch.dict(LIMITS, {"document": (1, timedelta(days=1))}):
            self.send(self.librarian, "upload", file=upload("one.pdf"))
            self.send(self.librarian, "upload", file=upload("two.pdf"))
        self.assertEqual(list(Document.objects.values_list("original_name", flat=True)), ["one.pdf"])

    def test_private_group_files_download_for_members_only_under_their_original_name(self):
        doc = self.document(self.secret, name="Pay bands 2026.pdf")
        url, path = doc.file.url, doc.file.path
        self.assertTrue(url.startswith("/media/library/"))
        self.assertEqual(self.download(self.alice, url)[0], 404)
        self.assertEqual(self.download(self.carol, url), (200, 'attachment; filename="Pay bands 2026.pdf"'))
        # Company files and files of public groups are open to every colleague.
        public = Community.objects.create(name="Running Club", slug="running-club")
        for community in (None, public):
            self.assertEqual(self.download(self.alice, self.document(community).file.url)[0], 200)
        # A file in the library folder that no document points to is never served.
        os.makedirs(os.path.join(TEMP_MEDIA, "library"), exist_ok=True)
        with open(os.path.join(TEMP_MEDIA, "library", "stray.pdf"), "wb") as fh:
            fh.write(b"%PDF")
        self.assertEqual(self.download(self.carol, "/media/library/stray.pdf")[0], 404)
        # Odd characters in the stored name can't reach the download header.
        Document.objects.filter(pk=doc.pk).update(original_name="..\\..\\pay/bands\r\n.pdf")
        self.assertEqual(self.download(self.carol, url)[1], 'attachment; filename="....paybands.pdf"')
        # Deleting the document removes the file from disk.
        self.assertTrue(os.path.exists(path))
        doc.delete()
        self.assertFalse(os.path.exists(path))

    def test_folders_nest_show_breadcrumbs_and_only_go_when_empty(self):
        self.assertEqual(self.send(self.alice, "folder_new", name="Mine").status_code, 403)
        self.send(self.librarian, "folder_new", name="Policies")
        policies = Folder.objects.get(name="Policies")
        self.send(self.librarian, "folder_new", name="2026", folder=policies.pk)
        year = Folder.objects.get(name="2026")
        self.assertEqual(year.parent, policies)
        self.send(self.librarian, "upload", folder=year.pk, file=upload("Travel policy.pdf"))
        self.assertEqual(Document.objects.get().folder, year)

        top = self.client.get(reverse("library:files"))
        self.assertContains(top, "Policies")
        self.assertNotContains(top, "Travel policy")  # it lives two folders down
        inside = self.client.get(reverse("library:files"), {"folder": year.pk})
        self.assertEqual(inside.context["crumbs"], [policies, year])
        self.assertContains(inside, f'<a href="?folder={policies.pk}">Policies</a>', html=True)
        self.assertContains(inside, "Travel policy")
        # Searching looks through every folder, by title and by file name.
        self.assertContains(self.client.get(reverse("library:files"), {"q": "travel"}), "Travel policy")
        self.assertNotContains(self.client.get(reverse("library:files"), {"q": "expenses"}), "Travel policy")
        # A company folder can't be opened through a group's page, nor a group's folder through the company page.
        group_folder = Folder.objects.create(name="Hidden", community=self.secret)
        self.assertEqual(self.client.get(reverse("library:files"), {"folder": group_folder.pk}).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("library:group_files", args=["pay-review"]), {"folder": year.pk}).status_code, 404)

        self.assertEqual(self.send(self.alice, "folder_delete", year.pk).status_code, 403)
        self.send(self.librarian, "folder_delete", policies.pk)  # holds a folder
        self.send(self.librarian, "folder_delete", year.pk)  # holds a file
        self.assertEqual(Folder.objects.filter(community=None).count(), 2)
        self.send(self.librarian, "document_delete", Document.objects.get().pk)
        self.send(self.librarian, "folder_delete", year.pk)
        self.send(self.librarian, "folder_delete", policies.pk)
        self.assertFalse(Folder.objects.filter(community=None).exists())

    def test_file_pages_render_and_private_group_pages_are_hidden_from_outsiders(self):
        self.document(self.secret, name="Pay bands.pdf")
        self.document(name="Staff handbook.pdf")
        self.client.force_login(self.carol)
        company = self.client.get(reverse("library:files"))
        self.assertContains(company, "Staff handbook")
        self.assertNotContains(company, "Pay bands")
        self.assertNotContains(company, "Add a file")  # Carol may only read
        self.assertContains(self.client.get(reverse("library:files"), {"tab": "groups"}), "Pay Review")
        self.assertContains(self.client.get(reverse("library:files"), {"tab": "recent"}), "Pay bands")
        group_page = self.client.get(reverse("library:group_files", args=["pay-review"]))
        self.assertContains(group_page, "Pay bands")
        self.assertTemplateUsed(group_page, "hub/_group_tabs.html")
        self.assertContains(self.client.get(reverse("library:group_featured", args=["pay-review"])), "No featured files yet")

        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(reverse("library:files"), {"tab": "recent"}), "Pay bands")
        for name in ("group_files", "group_featured"):
            self.assertEqual(self.client.get(reverse(f"library:{name}", args=["pay-review"])).status_code, 404)
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse("library:group_files", args=["pay-review"])), "Add a file")

    # --- featured ------------------------------------------------------------------
    def test_featured_links_must_be_web_addresses_and_need_the_right_to_add_them(self):
        good = {"title": "Payslips", "url": "https://payroll.example.com/login"}
        self.assertEqual(self.send(self.alice, "link_new", **good).status_code, 403)
        self.assertEqual(self.send(self.carol, "link_new", community="pay-review", **good).status_code, 403)
        for bad in ("javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
                    "ftp://files.example.com/a", "//example.com", "payroll.example.com", ""):
            self.send(self.librarian, "link_new", title="Bad", url=bad)
        self.send(self.librarian, "link_new", title="", url=good["url"])
        self.assertFalse(FeaturedLink.objects.exists())

        self.send(self.librarian, "link_new", **good)
        self.send(self.bob, "link_new", community="pay-review", title="Pay calculator", url="http://pay.example.com")
        company, group = FeaturedLink.objects.order_by("pk")
        self.assertEqual((company.community, group.community), (None, self.secret))
        page = self.client.get(reverse("library:featured"))
        self.assertContains(
            page, '<a class="row-title" href="https://payroll.example.com/login" target="_blank" rel="noopener noreferrer">Payslips</a>',
            html=True,
        )
        self.assertNotContains(page, "Pay calculator")
        self.assertContains(self.client.get(reverse("library:group_featured", args=["pay-review"])), "Pay calculator")

        self.assertEqual(self.send(self.carol, "link_delete", group.pk).status_code, 403)
        self.assertEqual(self.send(self.bob, "link_delete", company.pk).status_code, 403)
        self.send(self.bob, "link_delete", group.pk)
        self.send(self.librarian, "link_delete", company.pk)
        self.assertFalse(FeaturedLink.objects.exists())

    def test_files_can_be_featured_by_those_who_may(self):
        doc, group_doc = self.document(), self.document(self.secret, name="Pay bands.pdf")
        self.assertEqual(self.send(self.alice, "document_feature", doc.pk, featured="1").status_code, 403)
        self.assertEqual(self.send(self.carol, "document_feature", group_doc.pk, featured="1").status_code, 403)
        self.assertNotContains(self.client.get(reverse("library:featured")), "Staff handbook")
        self.send(self.librarian, "document_feature", doc.pk, featured="1")
        self.send(self.bob, "document_feature", group_doc.pk, featured="1")
        page = self.client.get(reverse("library:featured"))
        self.assertContains(page, "Staff handbook")
        self.assertNotContains(page, "Pay bands")
        self.assertContains(self.client.get(reverse("library:group_featured", args=["pay-review"])), "Pay bands")
        self.send(self.librarian, "document_feature", doc.pk, featured="0")
        self.assertFalse(Document.objects.get(pk=doc.pk).is_featured)

    # --- knowledge base ------------------------------------------------------------
    def test_only_editors_can_change_the_knowledge_base(self):
        self.assertContains(self.client.get(reverse("library:kb")), "The knowledge base is empty")
        category = Category.objects.create(name="HR")
        article = Article.objects.create(category=category, title="Holidays", body="Book in advance.")
        fields = {"category": category.pk, "title": "Expenses", "body": "Keep **every** receipt. <script>alert(1)</script>"}
        for user in (self.alice, self.bob):
            self.assertEqual(self.send(user, "article_new", **fields).status_code, 403)
            self.assertEqual(self.send(user, "article_edit", article.pk, **fields).status_code, 403)
            self.assertEqual(self.send(user, "article_delete", article.pk).status_code, 403)
            self.assertEqual(self.send(user, "category_new", name="IT").status_code, 403)
            self.assertEqual(self.client.get(reverse("library:article_new")).status_code, 403)
            self.assertNotContains(self.client.get(article.get_absolute_url()), "Edit article")
        self.assertEqual(list(Article.objects.values_list("title", flat=True)), ["Holidays"])

        self.send(self.librarian, "category_new", name="IT")
        self.assertTrue(Category.objects.filter(name="IT").exists())
        self.send(self.librarian, "article_new", **fields)
        expenses = Article.objects.get(title="Expenses")
        self.assertEqual((expenses.created_by, expenses.updated_by), (self.librarian, self.librarian))
        page = self.client.get(expenses.get_absolute_url())
        self.assertContains(page, "<strong>every</strong>")
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;")  # typed HTML stays text
        self.assertContains(page, "Edit article")
        self.send(self.librarian, "article_edit", article.pk, **{**fields, "title": "Annual leave", "is_legal": "on"})
        article.refresh_from_db()
        self.assertEqual((article.title, article.is_legal, article.created_by, article.updated_by), ("Annual leave", True, None, self.librarian))
        self.assertEqual(self.client.get(reverse("library:article_delete", args=[expenses.pk])).status_code, 405)
        self.send(self.librarian, "article_delete", expenses.pk)
        self.assertFalse(Article.objects.filter(pk=expenses.pk).exists())

    def test_knowledge_base_lists_searches_and_shows_legal_articles(self):
        hr, it = Category.objects.create(name="HR", position=1), Category.objects.create(name="IT", position=2)
        Article.objects.create(category=hr, title="Holidays", body="Book annual leave in advance.")
        Article.objects.create(category=it, title="Wi-Fi", body="Join the Staff network.")
        Article.objects.create(category=hr, title="Privacy notice", body="How we use your data.", is_legal=True)
        kb = self.client.get(reverse("library:kb"))
        for text in ("HR", "IT", "Holidays", "Wi-Fi", "Privacy notice"):
            self.assertContains(kb, text)
        self.assertNotContains(kb, "New article")

        def found(q):
            return [a.title for a in self.client.get(reverse("library:kb"), {"q": q}).context["results"]]

        self.assertEqual(found("holidays"), ["Holidays"])  # in the title
        self.assertEqual(found("staff NETWORK"), ["Wi-Fi"])  # in the text, any order, any case
        self.assertEqual(found("payroll"), [])
        legal = self.client.get(reverse("library:legal"))
        self.assertContains(legal, "Privacy notice")
        self.assertNotContains(legal, "Holidays")

    # --- hooks ---------------------------------------------------------------------
    def test_library_plugs_into_the_menu_search_downloads_and_data_export(self):
        for row in [(30, "Knowledge base", "library:kb", "book"), (50, "Featured", "library:featured", "star"),
                    (70, "Files", "library:files", "folder")]:
            self.assertIn(row, plugins.MENU)
            self.assertEqual(self.client.get(reverse(row[2])).status_code, 200)
        self.assertIs(plugins.MEDIA_GUARDS["library"], hooks.media_guard)
        for hook in (hooks.search_files, hooks.search_kb):
            self.assertIn(hook, plugins.SEARCH_PROVIDERS)
        self.assertIn(hooks.export, plugins.EXPORTERS)

        handbook = self.document(name="Staff handbook.pdf")
        self.document(self.secret, name="Handbook for pay reviews.pdf", uploaded_by=self.bob)
        article = Article.objects.create(
            category=Category.objects.create(name="HR"), title="Handbook guide", body="Read it.", created_by=self.librarian
        )
        self.assertEqual(
            hooks.search_files(self.alice, "handbook", 5), ("Files", [("Staff handbook", handbook.file.url, "Staff handbook.pdf · Company")])
        )
        self.assertEqual(len(hooks.search_files(self.carol, "handbook", 5)[1]), 2)  # members also find the group's file
        self.assertEqual(len(hooks.search_files(self.carol, "handbook", 1)[1]), 1)
        self.assertEqual(hooks.search_kb(self.alice, "guide", 5), ("Knowledge base", [("Handbook guide", article.get_absolute_url(), "HR")]))
        self.assertEqual(hooks.search_kb(self.alice, "payroll", 5)[1], [])

        key, data, paths = hooks.export(self.librarian)
        self.assertEqual((key, paths), ("library", []))
        self.assertEqual([d["original_name"] for d in data["documents"]], ["Staff handbook.pdf"])
        self.assertEqual([a["title"] for a in data["articles"]], ["Handbook guide"])
        self.assertEqual(hooks.export(self.alice)[1], {"documents": [], "articles": []})
