"""ModelForm for UserPreference — paired with views.preferences."""

from __future__ import annotations

from django import forms

from apps.accounts.models import UserPreference


class UserPreferenceForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = UserPreference
        fields = ["theme", "dashboard_window_days", "redact_audit_screenshots"]
        widgets = {
            "theme": forms.Select(attrs={"class": "input"}),
            "dashboard_window_days": forms.NumberInput(
                attrs={"class": "input", "min": "1", "max": "365"}
            ),
            "redact_audit_screenshots": forms.CheckboxInput(),
        }

    def clean_dashboard_window_days(self) -> int:
        value = self.cleaned_data["dashboard_window_days"]
        if value < 1 or value > 365:
            raise forms.ValidationError("Window must be between 1 and 365 days.")
        return int(value)
