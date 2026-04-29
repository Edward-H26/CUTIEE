"""Render docs/REPORT.md to docs/REPORT.pdf via pandoc + Playwright.

Pandoc converts the Markdown to a styled HTML file with GitHub-flavored
CSS plus syntax highlighting, then Playwright loads the HTML in a
headless Chromium and emits a PDF using Chrome's print pipeline. We use
this chain because the project already depends on Playwright; adding
weasyprint or a TeX distribution just for one report would be heavier.

Usage:
    uv run python scripts/build_report_pdf.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = REPO_ROOT / "docs" / "REPORT.md"
OUTPUT_PDF = REPO_ROOT / "docs" / "REPORT.pdf"
PANDOC_CSS_URL = (
    "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/"
    "github-markdown.min.css"
)


def runPandocToHtml(htmlPath: Path) -> None:
    cmd = [
        "pandoc",
        str(SOURCE_MD),
        "-o", str(htmlPath),
        "--standalone",
        "--metadata", "title=CUTIEE Technical Report",
        "--metadata", "author=INFO490 A10 Submission",
        f"--css={PANDOC_CSS_URL}",
        "--highlight-style=tango",
    ]
    result = subprocess.run(cmd, capture_output = True, text = True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"pandoc failed: {result.returncode}")


def renderHtmlToPdf(htmlPath: Path, pdfPath: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(htmlPath.as_uri(), wait_until = "networkidle")
            page.emulate_media(media = "print")
            page.pdf(
                path = str(pdfPath),
                format = "Letter",
                margin = {
                    "top": "0.75in",
                    "right": "0.75in",
                    "bottom": "0.75in",
                    "left": "0.75in",
                },
                print_background = True,
            )
        finally:
            browser.close()


def main() -> int:
    if not SOURCE_MD.exists():
        sys.stderr.write(f"missing source markdown: {SOURCE_MD}\n")
        return 1
    OUTPUT_PDF.parent.mkdir(parents = True, exist_ok = True)
    with tempfile.NamedTemporaryFile(suffix = ".html", delete = False) as tmp:
        htmlPath = Path(tmp.name)
    try:
        runPandocToHtml(htmlPath)
        renderHtmlToPdf(htmlPath, OUTPUT_PDF)
    finally:
        htmlPath.unlink(missing_ok = True)
    print(f"Wrote {OUTPUT_PDF.relative_to(REPO_ROOT)} ({OUTPUT_PDF.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
