"""Capture UI screenshots referenced by docs/REPORT.md.

Drives a running CUTIEE dev server with Playwright and saves PNGs into
`docs/screenshots/`. Five panels are captured:

    01-landing.png      / public landing page
    02-login.png        /accounts/login/ allauth form
    03-tasks.png        /tasks/ workspace (logged in)
    04-detail.png       /tasks/dashboard/ as the closest persistent detail-style view
    05-dashboard.png    /tasks/dashboard/ cost dashboard (logged in)

Pages 01 and 02 are public so they capture without auth. The three
logged-in pages need a session cookie issued by the running server
(in-memory SQLite is per-process, so cross-process force_login does not
work). The script therefore drives Playwright through allauth's signup
and login flow against the live server. Sessions then persist within
Playwright's context and the protected pages render normally.

Prerequisites:
    1. `CUTIEE_ENV=local` set in the environment.
    2. Django dev server up at http://localhost:8000 (run `./scripts/dev.sh`
       or `uv run python manage.py runserver 0.0.0.0:8000 --noreload`).

Usage:
    uv run python scripts/capture_screenshots.py
"""
from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
DEFAULT_BASE_URL = "http://localhost:8000"


def signupAndLogin(page: object, baseUrl: str) -> None:
    """Sign up a fresh throwaway user and follow the auth flow.

    allauth's signup view auto-logs the new user in (email verification
    is configured as optional in `cutiee_site/settings.py:241`) so the
    page lands on `/tasks/` after submission. Using a unique email per
    run keeps the screenshot sweep idempotent across reruns.
    """
    email = f"capturer-{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(16)

    page.goto(  # type: ignore[attr-defined]
        baseUrl + "/accounts/signup/",
        wait_until = "networkidle",
        timeout = 20_000,
    )
    page.fill("input[name='email']", email)  # type: ignore[attr-defined]
    page.fill("input[name='password1']", password)  # type: ignore[attr-defined]
    page.fill("input[name='password2']", password)  # type: ignore[attr-defined]
    page.click("button[type='submit']")  # type: ignore[attr-defined]
    page.wait_for_load_state("networkidle", timeout = 20_000)  # type: ignore[attr-defined]


def submitDemoTask(page: object, baseUrl: str) -> str | None:
    """Submit a sample task so 04-detail.png can show a real task page.

    Returns the URL of the newly created task detail page, or None if
    the submit form did not redirect cleanly. The form lives on
    /tasks/ and is the same one a user types into; failures here mean
    something is off with the dev server, not the script.
    """
    page.goto(baseUrl + "/tasks/", wait_until = "networkidle", timeout = 20_000)  # type: ignore[attr-defined]
    page.fill(  # type: ignore[attr-defined]
        "textarea[name='description']",
        "Open the demo spreadsheet and read row 1.",
    )
    page.fill("input[name='initial_url']", "http://localhost:5001/")  # type: ignore[attr-defined]
    page.click("button[data-testid='submit-task']")  # type: ignore[attr-defined]
    page.wait_for_load_state("networkidle", timeout = 20_000)  # type: ignore[attr-defined]
    currentUrl = str(page.url)  # type: ignore[attr-defined]
    if "/tasks/" in currentUrl and currentUrl.rstrip("/") != baseUrl + "/tasks":
        return currentUrl
    return None


def capture(baseUrl: str) -> None:
    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents = True, exist_ok = True)

    publicTargets = [
        ("01-landing.png", "/"),
        ("02-login.png", "/accounts/login/"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport = {"width": 1280, "height": 800})
            page = ctx.new_page()

            for filename, path in publicTargets:
                page.goto(baseUrl + path, wait_until = "networkidle", timeout = 20_000)
                time.sleep(0.5)
                page.screenshot(path = str(OUT_DIR / filename), full_page = True)
                print(f"captured {filename}")

            signupAndLogin(page, baseUrl)
            print("logged in via allauth signup flow")

            page.goto(baseUrl + "/tasks/", wait_until = "networkidle", timeout = 20_000)
            time.sleep(0.5)
            page.screenshot(path = str(OUT_DIR / "03-tasks.png"), full_page = True)
            print("captured 03-tasks.png")

            detailUrl = submitDemoTask(page, baseUrl)
            if detailUrl:
                page.goto(detailUrl, wait_until = "networkidle", timeout = 20_000)
                time.sleep(0.5)
                page.screenshot(path = str(OUT_DIR / "04-detail.png"), full_page = True)
                print(f"captured 04-detail.png from {detailUrl}")
            else:
                page.goto(baseUrl + "/me/preferences/", wait_until = "networkidle", timeout = 20_000)
                time.sleep(0.5)
                page.screenshot(path = str(OUT_DIR / "04-detail.png"), full_page = True)
                print("captured 04-detail.png (fell back to /me/preferences/ since task submit did not redirect)")

            page.goto(baseUrl + "/tasks/dashboard/", wait_until = "networkidle", timeout = 20_000)
            time.sleep(0.5)
            page.screenshot(path = str(OUT_DIR / "05-dashboard.png"), full_page = True)
            print("captured 05-dashboard.png")

            ctx.close()
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default = DEFAULT_BASE_URL)
    args = parser.parse_args()

    capture(args.base_url)
    print(f"\nSaved 5 PNGs to {OUT_DIR.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
