"""Django form for task submission.

A plain `forms.Form` because tasks are persisted into Neo4j, not Django ORM.
The view layer reads `cleaned_data` and calls `apps.tasks.repo.createTask`.
"""
from __future__ import annotations

from django import forms


class TaskSubmissionForm(forms.Form):
    description = forms.CharField(
        label = "What should the agent do?",
        max_length = 800,
        widget = forms.Textarea(
            attrs = {
                "rows": 3,
                "placeholder": "Sort the spreadsheet rows by column B and email me the result.",
                "class": "task-input",
            }
        ),
    )
    initial_url = forms.URLField(
        label = "Starting URL (optional)",
        required = False,
        widget = forms.URLInput(
            attrs = {
                "placeholder": "https://docs.google.com/spreadsheets/...",
                "class": "task-input",
            }
        ),
    )
    domain_hint = forms.CharField(
        label = "Domain hint (optional)",
        required = False,
        max_length = 120,
    )

    def cleanedTuple(self) -> tuple[str, str, str]:
        return (
            self.cleaned_data["description"].strip(),
            self.cleaned_data.get("initial_url") or "",
            self.cleaned_data.get("domain_hint") or "",
        )
