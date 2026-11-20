from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q

from hub.media import process_upload
from hub.models import Community

from .models import Journey, Step


class JourneyForm(forms.ModelForm):
    class Meta:
        model = Journey
        fields = ["title", "description", "cover", "audiences"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "cover": forms.FileInput(attrs={"accept": "image/*"}),
            "audiences": forms.CheckboxSelectMultiple,
        }
        labels = {"cover": "Cover picture (optional)", "audiences": "Who is it for?"}
        help_texts = {"audiences": "Tick groups or teams. Leave them all empty to give it to everyone."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.old_cover = self.instance.cover.name
        # Private groups stay hidden from editors who aren't members. Ones already chosen stay, so saving keeps them.
        allowed = Q(kind=Community.UNIT) | Q(is_private=False) | Q(members=user)
        if self.instance.pk:
            allowed |= Q(journeys=self.instance)
        self.fields["audiences"].queryset = Community.objects.filter(allowed).distinct()

    def clean_cover(self):
        cover = self.cleaned_data.get("cover")
        if isinstance(cover, UploadedFile):
            cover, _ = process_upload(cover, video=False)
        return cover

    def save(self, commit=True):
        journey = super().save(commit)
        if self.old_cover and self.old_cover != journey.cover.name:
            journey.cover.storage.delete(self.old_cover)  # a replaced cover must not stay on disk
        return journey


class StepForm(forms.ModelForm):
    # Declared here to choose https for addresses typed without "http://" (Django 5 warns otherwise).
    link_url = forms.URLField(required=False, max_length=500, assume_scheme="https", label="Link (optional)")

    class Meta:
        model = Step
        fields = ["title", "body", "link_url", "position"]
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}
        labels = {"body": "Text", "position": "Place in the journey"}
        help_texts = {
            "body": "You can use **bold**, *italic* and lists (start a line with - or 1.).",
            "position": "1 comes first.",
        }
