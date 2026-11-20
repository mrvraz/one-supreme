import shutil
import tempfile
from io import StringIO

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from hub.models import Attachment, Community, Post, User

TEMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA, ALLOW_PASSWORD_LOGIN=True)
class DemoServerTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def test_public_demo_only_lets_the_new_logins_in(self):
        call_command("seed_demo", "--force", stdout=StringIO())  # tests run with DEBUG off, like a demo server
        # The shared demo password is in the code, so it must not work on a public server.
        self.assertFalse(User.objects.get(username="amelia").has_usable_password())

        out = StringIO()
        call_command("demo_logins", "Amy", "Chambers", "--force", stdout=out)
        password = out.getvalue().strip().rsplit(": ", 1)[1]
        admin, staff = User.objects.get(username="amy.admin"), User.objects.get(username="amy.staff")
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.communities.filter(is_private=True).exists())  # sees the private group too
        self.assertFalse(staff.is_staff or staff.is_superuser)
        self.assertTrue(staff.communities.filter(slug="marketing").exists())
        self.assertTrue(self.client.login(username="amy.staff", password=password))
        self.assertTrue(self.client.login(username="amy.admin", password=password))

        # Running it again gives a new password and no duplicate accounts.
        call_command("demo_logins", "Amy", "Chambers", "--force", stdout=StringIO())
        self.assertEqual(User.objects.filter(username__startswith="amy.").count(), 2)
        self.assertFalse(self.client.login(username="amy.staff", password=password))

    def test_refresh_pictures_keeps_the_demo(self):
        call_command("seed_demo", "--force", stdout=StringIO())
        social = Post.objects.get(body__startswith="What a turnout")
        # What an older demo had: a fourth photo on this post, a group cover, and a photo a person uploaded.
        extra = Attachment.objects.create(post=social, file=ContentFile(b"old", name="demo-13.jpg"), kind=Attachment.IMAGE)
        mine = Attachment.objects.create(post=social, file=ContentFile(b"mine", name="holiday.jpg"), kind=Attachment.IMAGE)
        group = Community.objects.get(slug="running-club")
        group.cover.save("demo-500.jpg", ContentFile(b"old"))
        posts = Post.objects.count()

        call_command("seed_demo", "--refresh-pictures", "--force", stdout=StringIO())

        self.assertFalse(Attachment.objects.filter(pk=extra.pk).exists())
        self.assertEqual(Attachment.objects.get(pk=mine.pk).file.read(), b"mine")  # left alone
        group.refresh_from_db()
        self.assertFalse(group.cover)
        self.assertEqual(Post.objects.count(), posts)
        news = Post.objects.filter(kind=Post.NEWS).first()
        self.assertEqual(Image.open(news.cover).size, (1200, 630))  # a real photo, cropped for a news cover
        self.assertRegex(news.cover.name, r"demo-\d+-photo(_\w+)?\.jpg$")  # a new name, so browsers fetch it afresh
