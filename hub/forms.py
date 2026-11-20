from datetime import date, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from .media import process_upload
from .models import NOTIFY_TYPES, REMINDER_CHOICES, Attachment, Comment, Community, Event, PollOption, Post, Report, User
from .security import LIMIT_MESSAGE, over_limit

MAX_FILES = 10
# Same limit as nginx's client_max_body_size (which adds a little room for the text), so nginx never refuses first.
MAX_POST_MB = 250
UPLOAD_ACCEPT = "image/*,video/mp4,video/webm,video/quicktime"
DATETIME = {"widget": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A file field that accepts several files (pattern from the Django docs)."""

    def __init__(self, *args, **kwargs):
        attrs = {"accept": UPLOAD_ACCEPT, "class": "sr-only", "data-max-total": MAX_POST_MB * 1024 * 1024}
        kwargs.setdefault("widget", MultipleFileInput(attrs=attrs))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        items = data if isinstance(data, (list, tuple)) else [data]
        return [f for f in (super(MultipleFileField, self).clean(d, initial) for d in items) if f]


def clean_picture(upload, max_side):
    """A single optional picture field: checked, resized and stripped of location data."""
    if isinstance(upload, UploadedFile):
        upload, _ = process_upload(upload, max_side=max_side, video=False)
    return upload


def clean_publish_time(when):
    if when and when < timezone.now() - timedelta(minutes=1):
        raise ValidationError("Pick a time in the future, or leave this empty to post now.")
    if when and when > timezone.now() + timedelta(days=366):
        raise ValidationError("You can schedule up to a year ahead.")
    return when


class PostForm(forms.ModelForm):
    """The composer for posts and polls. News has its own form."""

    files = MultipleFileField(required=False, label="Photos or videos")
    # shortcut: one description is used for every photo in the post; add per-photo text if staff ask for it.
    alt_text = forms.CharField(required=False, max_length=300, label="Describe the photos for people using screen readers")
    poll_options = forms.CharField(
        required=False, label="Poll answers", widget=forms.Textarea(attrs={"rows": 4, "placeholder": "One answer per line"})
    )
    poll_closes_at = forms.DateTimeField(required=False, label="Poll closes (optional)", **DATETIME)
    publish_at = forms.DateTimeField(required=False, label="Post later (optional)", **DATETIME)

    class Meta:
        model = Post
        fields = ["body", "community", "is_announcement"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "placeholder": "Share an update…", "data-mentions": ""})}
        labels = {"community": "Post to", "is_announcement": "Announcement: pin it and tell everyone"}

    def __init__(self, *args, user, community=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.fixed_community = user, community
        if community:
            del self.fields["community"]
        else:
            # Only groups and units you belong to can be posted into.
            self.fields["community"].queryset = user.communities.all()
            self.fields["community"].empty_label = "Everyone"
        if community or not user.is_staff:
            del self.fields["is_announcement"]

    def clean_body(self):
        body = self.cleaned_data["body"]
        if len(body) > 5000:
            raise ValidationError("Posts can be up to 5,000 characters. For something longer, publish it as news.")
        return body

    def clean_files(self):
        files = self.cleaned_data["files"]
        if len(files) > MAX_FILES:
            raise ValidationError(f"You can add up to {MAX_FILES} photos or videos to a post.")
        if sum(f.size for f in files) > MAX_POST_MB * 1024 * 1024:
            raise ValidationError(f"The photos and videos in one post must add up to less than {MAX_POST_MB} MB.")
        # Limits are checked here, before the slow photo and video processing.
        mine = {"user": self.user}
        if over_limit("post", Post.objects.filter(author=self.user), **mine) or (
            files
            and over_limit(
                "file", Attachment.objects.filter(post__author=self.user), adding=len(files), field="post__created_at", **mine
            )
        ):
            raise ValidationError(LIMIT_MESSAGE)
        return [process_upload(f) for f in files]

    def clean_poll_options(self):
        options = [line.strip() for line in self.cleaned_data["poll_options"].splitlines() if line.strip()]
        if options and not 2 <= len(options) <= 10:
            raise ValidationError("A poll needs between 2 and 10 answers, one per line.")
        if any(len(option) > 200 for option in options):
            raise ValidationError("Keep each answer under 200 characters.")
        return options

    def clean_publish_at(self):
        return clean_publish_time(self.cleaned_data["publish_at"])

    def clean(self):
        data = super().clean()
        has_text = bool(data.get("body", "").strip())
        if "files" not in self.errors and not has_text and not data.get("files"):
            raise ValidationError("Write something or add a photo.")
        if data.get("poll_options") and not has_text:
            raise ValidationError("Write the question for your poll.")
        closes = data.get("poll_closes_at")
        if data.get("poll_options") and closes and closes <= (data.get("publish_at") or timezone.now()):
            raise ValidationError("The poll must close after it opens.")
        if data.get("is_announcement") and data.get("community"):
            raise ValidationError("Announcements go to everyone, so post them to Everyone.")
        return data

    def save(self, commit=True):
        data = self.cleaned_data
        post = super().save(commit=False)
        post.author = self.user
        post.kind = Post.POLL if data["poll_options"] else Post.UPDATE
        post.poll_closes_at = data["poll_closes_at"] if data["poll_options"] else None
        if self.fixed_community:
            post.community = self.fixed_community
        post.created_at = post.last_activity_at = data["publish_at"] or timezone.now()
        if post.is_announcement:
            post.pinned_at = post.created_at
        post.save()
        for file, kind in data["files"]:
            Attachment.objects.create(post=post, file=file, kind=kind, alt_text=data["alt_text"])
            if hasattr(file, "workdir"):  # a cleaned video's temporary folder
                file.close()
                file.workdir.cleanup()
        PollOption.objects.bulk_create(PollOption(post=post, text=text, position=i) for i, text in enumerate(data["poll_options"]))
        return post


class PostEditForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6, "data-mentions": ""})}
        labels = {"body": "Text"}

    def clean_body(self):
        body = self.cleaned_data["body"]
        if not body.strip() and not self.instance.attachments.exists():
            raise ValidationError("A post needs some text or a photo.")
        return body


class NewsForm(forms.ModelForm):
    publish_at = forms.DateTimeField(required=False, label="Publish later (optional)", **DATETIME)

    class Meta:
        model = Post
        fields = ["title", "cover", "body", "audiences", "requires_ack"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Title of your news"}),
            "body": forms.Textarea(attrs={"rows": 12, "placeholder": "Write your news item…", "data-mentions": ""}),
            "cover": forms.FileInput(attrs={"accept": "image/*"}),
            "audiences": forms.CheckboxSelectMultiple,
        }
        labels = {
            "cover": "Cover picture (optional)",
            "audiences": "Who is it for? Tick none to send it to everyone.",
            "requires_ack": "Ask readers to confirm they've read it",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = True
        self.fields["body"].required = True
        self.fields["audiences"].queryset = Community.objects.order_by("kind", "name")
        if self.instance.pk and self.instance.is_scheduled:
            self.fields["publish_at"].initial = timezone.localtime(self.instance.created_at)

    def clean_cover(self):
        return clean_picture(self.cleaned_data.get("cover"), 1600)

    def clean_publish_at(self):
        return clean_publish_time(self.cleaned_data["publish_at"])

    def save(self, author, as_draft):
        post = super().save(commit=False)
        was_live = post.pk and post.is_live
        post.kind, post.is_draft = Post.NEWS, as_draft
        if not post.pk:
            post.author = author
        if was_live:
            post.edited_at = timezone.now()  # already published: keep its date, mark it edited
        else:
            post.created_at = post.last_activity_at = self.cleaned_data["publish_at"] or timezone.now()
        post.save()
        self.save_m2m()
        return post


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body", "image"]

    def clean_image(self):
        return clean_picture(self.cleaned_data.get("image"), 1280)

    def clean(self):
        data = super().clean()
        if "image" not in self.errors and not data.get("body", "").strip() and not data.get("image"):
            raise ValidationError("Write a comment or add a picture.")
        return data


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 4})}
        labels = {"reason": "What's wrong?"}

    def clean_reason(self):
        reason = self.cleaned_data["reason"]
        if len(reason) > 1000:
            raise ValidationError("Please keep it under 1,000 characters.")
        return reason


class ProfileForm(forms.ModelForm):
    birthday_day = forms.TypedChoiceField(
        required=False, coerce=int, empty_value=None, label="Birthday: day", choices=[("", "Day")] + [(d, d) for d in range(1, 32)]
    )
    birthday_month = forms.TypedChoiceField(
        required=False, coerce=int, empty_value=None, label="Birthday: month",
        choices=[("", "Month")] + list(enumerate(MONTHS, start=1)),
    )

    class Meta:
        model = User
        fields = ["avatar", "cover", "job_title", "department", "pronouns", "languages", "phone", "bio", "start_date"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
            "avatar": forms.FileInput(attrs={"accept": "image/*"}),
            "cover": forms.FileInput(attrs={"accept": "image/*"}),
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        labels = {"avatar": "Profile photo", "cover": "Cover picture"}
        help_texts = {
            "start_date": "Optional. Colleagues see the month and year you joined, and your work anniversary.",
            "phone": "Optional. Shown on your profile.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.birthday:
            self.fields["birthday_day"].initial = self.instance.birthday.day
            self.fields["birthday_month"].initial = self.instance.birthday.month
        self.fields["birthday_month"].help_text = (
            "Optional. Only the day and month are kept. Add it and colleagues see it on the Birthdays page; leave it empty to stay private."
        )

    def clean_avatar(self):
        return clean_picture(self.cleaned_data.get("avatar"), 512)

    def clean_cover(self):
        return clean_picture(self.cleaned_data.get("cover"), 1600)

    def clean(self):
        data = super().clean()
        day, month = data.get("birthday_day"), data.get("birthday_month")
        if bool(day) != bool(month):
            raise ValidationError("Pick both a day and a month for your birthday, or leave both empty.")
        try:
            data["birthday"] = date(2000, month, day) if day else None  # 2000 was a leap year, so 29 February fits
        except ValueError:
            raise ValidationError("That birthday isn't a real date.")
        return data

    def save(self, commit=True):
        self.instance.birthday = self.cleaned_data["birthday"]
        return super().save(commit)


class NotificationForm(forms.Form):
    """Per-type switches for push and for the daily email, plus do not disturb."""

    email_digest = forms.BooleanField(required=False, label="Send me the daily email summary")
    push_privacy = forms.ChoiceField(label="What a push notification shows", choices=User._meta.get_field("push_privacy").choices)
    dnd_from = forms.TimeField(required=False, label="Quiet hours start", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    dnd_to = forms.TimeField(required=False, label="Quiet hours end", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    dnd_weekends = forms.BooleanField(required=False, label="Quiet all weekend")

    def __init__(self, *args, user, **kwargs):
        self.user = user
        initial = {name: getattr(user, name) for name in ["email_digest", "push_privacy", "dnd_from", "dnd_to", "dnd_weekends"]}
        super().__init__(*args, initial=initial, **kwargs)
        for key in NOTIFY_TYPES:
            for channel in ("push", "email"):
                self.fields[f"{key}_{channel}"] = forms.BooleanField(required=False, initial=user.wants(key, channel))

    def rows(self):
        """For the template: one row per notification type with its two switches."""
        return [(label, self[f"{key}_push"], self[f"{key}_email"]) for key, (label, _push, _email) in NOTIFY_TYPES.items()]

    def clean(self):
        data = super().clean()
        if bool(data.get("dnd_from")) != bool(data.get("dnd_to")):
            raise ValidationError("Set both a start and an end for quiet hours, or leave both empty.")
        return data

    def save(self):
        data, user = self.cleaned_data, self.user
        for name in ["email_digest", "push_privacy", "dnd_from", "dnd_to", "dnd_weekends"]:
            setattr(user, name, data[name])
        user.notify_prefs = {key: {"push": data[f"{key}_push"], "email": data[f"{key}_email"]} for key in NOTIFY_TYPES}
        user.save(update_fields=["email_digest", "push_privacy", "dnd_from", "dnd_to", "dnd_weekends", "notify_prefs"])


class ReminderForm(forms.Form):
    reminders = forms.TypedMultipleChoiceField(
        required=False, coerce=int, choices=REMINDER_CHOICES, widget=forms.CheckboxSelectMultiple, label="Remind me"
    )


class PrivacyForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["share_email", "show_presence"]


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["look"]


class CommunityForm(forms.ModelForm):
    class Meta:
        model = Community
        fields = ["name", "description", "is_private", "cover"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "cover": forms.FileInput(attrs={"accept": "image/*"})}
        labels = {"cover": "Cover picture (optional)"}

    def clean_cover(self):
        return clean_picture(self.cleaned_data.get("cover"), 1600)


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ["title", "starts_at", "ends_at", "location", "community", "description"]
        widgets = {
            "starts_at": DATETIME["widget"],
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {"starts_at": "Starts", "ends_at": "Ends (optional)", "community": "Who's it for?"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        groups = Community.objects.filter(pk__in=user.communities.values("pk"))
        if self.instance.community_id:  # keep an edited event's group selectable even if the editor isn't a member
            groups = groups | Community.objects.filter(pk=self.instance.community_id)
        self.fields["community"].queryset = groups
        self.fields["community"].empty_label = "Everyone"

    def clean(self):
        data = super().clean()
        if data.get("starts_at") and data.get("ends_at") and data["ends_at"] < data["starts_at"]:
            raise ValidationError("The event can't end before it starts.")
        return data
