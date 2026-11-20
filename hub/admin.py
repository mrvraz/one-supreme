"""The admin site doubles as the moderation desk. Every moderator action is written to the audit log."""

import re

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import RSVP, Attachment, Comment, Community, Event, FeatureNote, Post, Report, User
from .security import audit


@admin.register(User)
class StaffUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Profile", {"fields": ("job_title", "department", "pronouns", "languages", "phone", "bio", "avatar", "cover", "birthday", "start_date")}),
        ("Settings", {"fields": ("share_email", "show_presence", "look", "email_digest", "dnd_on")}),
        ("Single sign-on", {"fields": ("sso_id",)}),
    )
    readonly_fields = ("sso_id",)
    list_display = ("email", "first_name", "last_name", "department", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name", "department")
    actions = ["unlink_sso"]

    @admin.action(description="Unlink single sign-on (their next sign-in with the same email links it again)")
    def unlink_sso(self, request, queryset):
        """For someone the directory re-created, e.g. a re-hire: they keep their old account and history."""
        for person in queryset.exclude(sso_id=None):
            person.sso_id = None
            person.save(update_fields=["sso_id"])
            self.log_change(request, person, "Unlinked from single sign-on")
            audit("sso_unlinked", request, user_id=person.pk, email=person.email)


def _set_hidden(modeladmin, request, queryset, hidden):
    for obj in queryset:
        obj.is_hidden = hidden
        obj.save(update_fields=["is_hidden"])
        modeladmin.log_change(request, obj, "Hidden by moderator" if hidden else "Made visible by moderator")
        audit("content_hidden" if hidden else "content_unhidden", request, item=f"{obj._meta.model_name} {obj.pk}")


@admin.action(description="Hide selected from staff")
def hide(modeladmin, request, queryset):
    _set_hidden(modeladmin, request, queryset, True)


@admin.action(description="Make selected visible again")
def unhide(modeladmin, request, queryset):
    _set_hidden(modeladmin, request, queryset, False)


@admin.action(description="Restore selected deleted items")
def restore(modeladmin, request, queryset):
    for obj in queryset.filter(deleted_at__isnull=False):
        obj.deleted_at = obj.deleted_by = None
        obj.save(update_fields=["deleted_at", "deleted_by"])
        modeladmin.log_change(request, obj, "Restored by moderator")
        audit("content_restored", request, item=f"{obj._meta.model_name} {obj.pk}")


class ModeratedAdmin(admin.ModelAdmin):
    """Shared by posts and comments: hidden and deleted items stay visible here for moderators and HR."""

    list_filter = ("is_hidden", ("deleted_at", admin.EmptyFieldListFilter))
    readonly_fields = ("deleted_at", "deleted_by")
    actions = [hide, unhide, restore]


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    fields = ("preview", "kind", "alt_text")
    readonly_fields = ("preview", "kind")

    @admin.display(description="File")
    def preview(self, obj):
        if obj.kind == Attachment.IMAGE:
            return format_html('<img src="{}" style="max-height:120px">', obj.file.url)
        return format_html('<a href="{}">Video</a>', obj.file.url)


@admin.register(Post)
class PostAdmin(ModeratedAdmin):
    list_display = ("__str__", "kind", "author", "community", "pinned_at", "is_hidden", "deleted_at", "created_at")
    list_filter = ModeratedAdmin.list_filter + ("kind", "is_announcement", "community")
    search_fields = ("body", "author__email", "author__first_name", "author__last_name")
    raw_id_fields = ("author",)
    inlines = [AttachmentInline]


@admin.register(Comment)
class CommentAdmin(ModeratedAdmin):
    list_display = ("__str__", "author", "post", "is_hidden", "deleted_at", "created_at")
    search_fields = ("body", "author__email")
    raw_id_fields = ("author", "post")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("__str__", "content", "reason", "reporter", "created_at", "resolved_at")
    list_filter = (("resolved_at", admin.EmptyFieldListFilter),)
    readonly_fields = ("reporter", "post", "comment", "person", "reason", "created_at", "resolved_at", "resolved_by", "content")
    actions = ["hide_and_resolve", "resolve"]

    def has_add_permission(self, request):
        return False  # reports come from staff using the Report link, not from the admin

    @admin.display(description="Reported content")
    def content(self, obj):
        target = obj.target
        if target is None:
            return "(removed for good)"
        if obj.person_id:
            url = reverse("admin:hub_user_change", args=[target.pk])
            person = format_html('<a href="{}">Person: {}</a>', url, target)
            # A chat report names the reported picture (see chat.views.report); moderators may open it.
            picture = re.search(r"^\(chat message \d+, sent .+, with picture (\S+)\)$", obj.reason, re.M)
            if picture:
                return format_html('{} · <a href="{}">Picture</a>', person, settings.MEDIA_URL + picture[1])
            return person
        state = " [hidden]" if target.is_hidden else ""
        state += " [deleted by author]" if target.deleted_at and target.deleted_by_id == target.author_id else ""
        state += " [deleted by moderator]" if target.deleted_at and target.deleted_by_id != target.author_id else ""
        url = reverse(f"admin:hub_{target._meta.model_name}_change", args=[target.pk])
        return format_html('<a href="{}">{}</a>{}', url, str(target)[:80], state)

    def _resolve(self, request, queryset, hide_target):
        for report in queryset.filter(resolved_at__isnull=True):
            if hide_target and report.target and not report.person_id:  # people can't be hidden; HR deals with them
                report.target.is_hidden = True
                report.target.save(update_fields=["is_hidden"])
                self.log_change(request, report.target, f"Hidden after {report}")
            report.resolved_at, report.resolved_by = timezone.now(), request.user
            report.save(update_fields=["resolved_at", "resolved_by"])
            self.log_change(request, report, "Resolved" + (" and content hidden" if hide_target else " with no action"))
            audit("report_resolved", request, report_id=report.pk, content_hidden=hide_target)

    @admin.action(description="Hide the reported content and close the report")
    def hide_and_resolve(self, request, queryset):
        self._resolve(request, queryset, hide_target=True)

    @admin.action(description="Close the report without action")
    def resolve(self, request, queryset):
        self._resolve(request, queryset, hide_target=False)


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    """Groups, and the organisation: business units, departments, locations and teams."""

    list_display = ("name", "kind", "unit_type", "is_private", "parent", "created_at")
    list_filter = ("kind", "unit_type", "is_private")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members", "admins")
    fields = ("name", "slug", "kind", "unit_type", "parent", "is_private", "description", "cover", "members", "admins")


@admin.register(FeatureNote)
class FeatureNoteAdmin(admin.ModelAdmin):
    """Entries on the "What's new" page."""

    list_display = ("title", "published_at")


class RSVPInline(admin.TabularInline):
    model = RSVP
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "starts_at", "community", "created_by")
    list_filter = ("community",)
    search_fields = ("title", "location")
    raw_id_fields = ("created_by",)
    inlines = [RSVPInline]


@admin.register(LogEntry)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only history of what admins and moderators changed."""

    list_display = ("action_time", "user", "content_type", "object_repr", "action_flag", "change_message")
    list_filter = ("action_flag", "content_type")
    search_fields = ("object_repr", "change_message", "user__email")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
