"""One-off helper: open a visible Chromium, let the user sign in, save cookies.

After the user signs into whatever sites the agent will visit
(Google, GitHub, etc.) and closes the window, the resulting
`storage_state.json` is written to data/storage_state.json. Setting
CUTIEE_STORAGE_STATE_PATH=data/storage_state.json in .env then makes
every Computer Use run start from that signed-in profile, so the agent
operates against the real Sheet instead of getting bounced to a login
screen.

Usage:
    uv run python scripts/capture_storage_state.py
    uv run python scripts/capture_storage_state.py --start-url https://docs.google.com/spreadsheets/
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

OUTPUT = Path("data/storage_state.json")


async def capture(startUrl: str) -> None:
    from playwright.async_api import async_playwright

    OUTPUT.parent.mkdir(parents = True, exist_ok = True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless = False, args = ["--start-maximized"])
        context = await browser.new_context(viewport = None)
        page = await context.new_page()
        if startUrl:
            await page.goto(startUrl)
        print(f"\nA Chromium window is open. Sign into the sites you want CUTIEE to operate against.")
        print(f"When you're done, close the window. The session will be saved to:\n  {OUTPUT.resolve()}\n")
        try:
            await page.wait_for_event("close", timeout = 0)
        except Exception:
            pass
        await context.storage_state(path = str(OUTPUT))
        await browser.close()
    print(f"Saved storage_state to {OUTPUT}.")
    print(f"Now set CUTIEE_STORAGE_STATE_PATH={OUTPUT} in your .env and re-run the task.")


def main() -> None:
    parser = argparse.ArgumentParser(description = "Capture a Playwright storage_state.json")
    parser.add_argument(
        "--start-url",
        default = "https://accounts.google.com",
        help = "Where to land first (default: Google sign-in page)",
    )
    args = parser.parse_args()
    asyncio.run(capture(args.start_url))


if __name__ == "__main__":
    main()
