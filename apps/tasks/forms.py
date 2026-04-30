"""Django form for task submission.

A plain `forms.Form` because tasks are persisted into Neo4j, not Django ORM.
The view layer reads `cleaned_data` and calls `apps.tasks.repo.createTask`.

`clean_initial_url` enforces an SSRF blocklist on the starting URL so a
submitted task cannot drive Playwright into the cloud-metadata endpoint
(`169.254.169.254`), private RFC1918 ranges (`10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`), localhost, or non-HTTP schemes. Production tasks must
target a public HTTP(S) URL; localhost demos only run when `CUTIEE_ENV=local`,
in which case the gating predicate at `agent/memory/local_llm.shouldUseLocalLlmForUrl`
already restricts the localhost path to the developer machine. The block
list mirrors the one used by `urllib3` and `requests` for SSRF-safe URL
fetchers.
"""

from __future__ import annotations

from urllib.parse import urlparse

from django import forms
from django.conf import settings

from agent.harness.url_safety import ALLOWED_URL_SCHEMES, hostnameIsPrivateOrUnresolved


class TaskSubmissionForm(forms.Form):
    description = forms.CharField(
        label="What should the agent do?",
        max_length=800,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Sort the spreadsheet rows by column B and email me the result.",
                "class": "task-input",
            }
        ),
    )
    initial_url = forms.URLField(
        label="Starting URL (optional)",
        required=False,
        widget=forms.URLInput(
            attrs={
                "placeholder": "https://docs.google.com/spreadsheets/...",
                "class": "task-input",
            }
        ),
    )
    domain_hint = forms.CharField(
        label="Domain hint (optional)",
        required=False,
        max_length=120,
    )

    def clean_initial_url(self) -> str:
        url = self.cleaned_data.get("initial_url") or ""
        if not url:
            return url
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_URL_SCHEMES:
            raise forms.ValidationError("Only http and https URLs are accepted.")
        hostname = (parsed.hostname or "").lower()
        cutieeEnv = getattr(settings, "CUTIEE_ENV", "")
        if hostnameIsPrivateOrUnresolved(hostname) and cutieeEnv != "local":
            raise forms.ValidationError(
                "Private or unresolved network URLs are not accepted in production. "
                "Use a public http(s) URL or run the app in local mode."
            )
        return url

    def cleanedTuple(self) -> tuple[str, str, str]:
        return (
            self.cleaned_data["description"].strip(),
            self.cleaned_data.get("initial_url") or "",
            self.cleaned_data.get("domain_hint") or "",
        )
