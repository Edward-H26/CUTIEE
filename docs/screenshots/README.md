# UI screenshots

Five PNGs referenced by `docs/TECHNICAL-REPORT.md`:

| File | Page | Notes |
|---|---|---|
| `01-landing.png` | `/` (landing) | Public; captures without auth |
| `02-login.png` | `/accounts/login/` | Public; allauth form |
| `03-tasks.png` | `/tasks/` | Auth-required; submission form + recent tasks |
| `04-detail.png` | `/tasks/<id>/` | Auth-required; HTMX progress, audit trail |
| `05-dashboard.png` | `/tasks/dashboard/` | Auth-required; cost timeseries + CSV download |

## Reproducing the screenshots

Two scripts are provided:

1. **Live capture** (`scripts/capture_screenshots.py`)
   - Drives a running CUTIEE dev server with Playwright.
   - Creates a throwaway Django test user, signs them in via session
     cookie, and captures the auth-required pages.
   - Run against a started dev stack:
     ```bash
     ./scripts/dev.sh                           # in one terminal
     uv run python scripts/capture_screenshots.py
     ```

2. **Placeholder generation** (`scripts/make_placeholder_screenshots.py`)
   - Produces branded 1280x800 PNGs per page (no server required).
   - Used when a dev server is not available (CI, fresh checkout).
   - Run anytime:
     ```bash
     uv run python scripts/make_placeholder_screenshots.py
     ```

The placeholder generator is idempotent and overwrites existing files
unless they already contain real captures. Both scripts write to this
directory.
