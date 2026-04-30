from __future__ import annotations

from django import forms


class MarkStaleForm(forms.Form):
    """Validate the reason field accompanying a procedural-template stale toggle.

    Templates can be marked stale when the user notices the cached fragment
    no longer matches the live UI, when the curator's confidence falls
    below the replay threshold, or when a downstream error suggests a
    behavioural drift. Constraining the reason to a fixed enum keeps the
    audit trail useful for later eval analysis.
    """

    REASON_CHOICES = (
        ("user-marked", "User marked"),
        ("confidence-low", "Confidence below threshold"),
        ("error-detected", "Downstream error detected"),
    )

    reason = forms.ChoiceField(
        choices=REASON_CHOICES,
        initial="user-marked",
        required=False,
    )

    def cleanedReason(self) -> str:
        return str(self.cleaned_data.get("reason") or "user-marked")
