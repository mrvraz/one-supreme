"""The library: shared files in folders, featured links and files, and the knowledge base."""

import os

from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from hub.models import Community, matching


def _person():
    # Files and articles belong to the company, so they stay when the person who added them leaves.
    return models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+")


def _community():
    # Empty means company-wide. Otherwise the group or organisation unit it belongs to.
    return models.ForeignKey(Community, on_delete=models.CASCADE, null=True, blank=True, related_name="+")


class Folder(models.Model):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    community = _community()
    created_by = _person()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def path(self):
        """This folder and the folders above it, top first, for the breadcrumbs."""
        folders, folder = [], self
        while folder:
            folders.insert(0, folder)
            folder = folder.parent
        return folders


class DocumentQuerySet(models.QuerySet):
    def viewable_by(self, user):
        """Company-wide files, and files of the groups and units this person can open (see Community.can_view)."""
        if user.has_perm("hub.change_community"):
            return self
        open_to = Community.objects.filter(Q(kind=Community.GROUP, is_private=False) | Q(members=user) | Q(admins=user))
        return self.filter(Q(community__isnull=True) | Q(community__in=open_to))

    def search(self, q):
        return matching(self, q, "title", "original_name")


class Document(models.Model):
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    community = _community()
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="library/%Y/%m/", db_index=True)  # looked up on every download
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    uploaded_by = _person()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_featured = models.BooleanField(default=False)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    @property
    def kind(self):
        """ "PDF", "DOCX"…: the label on the file-type pill."""
        return os.path.splitext(self.file.name)[1][1:].upper()


@receiver(post_delete, sender=Document)
def _delete_document_file(sender, instance, **kwargs):
    # Deleted documents (also when their folder or group goes) must not stay behind on disk.
    instance.file.delete(save=False)


class FeaturedLink(models.Model):
    title = models.CharField(max_length=120)
    # shortcut: Django's check wants a full address, so "http://intranet/" (no dot) is refused; loosen if staff need it.
    url = models.CharField(
        "Web address",
        max_length=500,
        validators=[URLValidator(schemes=["http", "https"], message="Enter a web address that starts with http:// or https://.")],
    )
    community = _community()
    position = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers come first")
    created_by = _person()

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return self.title


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    position = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers come first")

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class ArticleQuerySet(models.QuerySet):
    def search(self, q):
        return matching(self, q, "title", "body")


class Article(models.Model):
    # PROTECT: removing a category must never silently remove its articles.
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="articles")
    title = models.CharField(max_length=200)
    body = models.TextField(
        max_length=20000, help_text="You can use **bold**, *italic*, ~~strikethrough~~, lists (- or 1.) and web links."
    )
    is_legal = models.BooleanField("Legal document", default=False, help_text="Also listed under Legal on the About page")
    created_by = _person()
    updated_by = _person()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("library:article", args=[self.pk])
