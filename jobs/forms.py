from django import forms
from django.utils import timezone

from .models import Vacancy


class VacancyForm(forms.ModelForm):
    class Meta:
        model = Vacancy
        fields = ["title", "location", "department", "contract_type", "salary", "closes_on", "description", "apply_url", "contact"]
        widgets = {
            "closes_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 10}),
            "apply_url": forms.URLInput(attrs={"placeholder": "https://"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # shortcut: one list of all active staff; switch to a people picker if it gets too long to scroll.
        self.fields["contact"].queryset = self.fields["contact"].queryset.order_by("first_name", "last_name")
        self.fields["contact"].empty_label = "No one"

    def clean_closes_on(self):
        day = self.cleaned_data["closes_on"]
        # An old vacancy keeps its old date when an editor fixes something else in it.
        if day and day < timezone.localdate() and "closes_on" in self.changed_data:
            raise forms.ValidationError("The closing date is in the past.")
        return day
