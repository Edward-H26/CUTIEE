"""Render markdown reports to PDF via pandoc + Playwright.

Pandoc converts the Markdown to a styled HTML file with GitHub-flavored
CSS plus syntax highlighting, then Playwright loads the HTML in a
headless Chromium and emits a PDF using Chrome's print pipeline. We use
this chain because the project already depends on Playwright; adding
weasyprint or a TeX distribution just for one report would be heavier.

Defaults to building docs/TECHNICAL-REPORT.md to docs/TECHNICAL-REPORT.pdf.
Pass --source and --output to build a different report (e.g. the condensed
docs/REPORT.md to docs/REPORT.pdf for the rubric-graded 4-6 page submission).

Usage:
    uv run python scripts/build_report_pdf.py
    uv run python scripts/build_report_pdf.py --source docs/REPORT.md --output docs/REPORT.pdf
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_MD = REPO_ROOT / "docs" / "TECHNICAL-REPORT.md"
DEFAULT_OUTPUT_PDF = REPO_ROOT / "docs" / "TECHNICAL-REPORT.pdf"
PANDOC_CSS_URL = (
    "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/" "github-markdown.min.css"
)


def runPandocToHtml(sourceMd: Path, htmlPath: Path, title: str) -> None:
    cmd = [
        "pandoc",
        str(sourceMd),
        "-o",
        str(htmlPath),
        "--standalone",
        "--embed-resources",
        f"--resource-path={sourceMd.parent}",
        "--metadata",
        f"title={title}",
        "--metadata",
        "author=INFO490 A10 Submission",
        f"--css={PANDOC_CSS_URL}",
        "--highlight-style=tango",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"pandoc failed: {result.returncode}")


def renderHtmlToPdf(htmlPath: Path, pdfPath: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-zygote", "--single-process"])
        try:
            page = browser.new_page()
            page.goto(htmlPath.as_uri(), wait_until="networkidle")
            page.emulate_media(media="print")
            page.pdf(
                path=str(pdfPath),
                format="Letter",
                margin={
                    "top": "0.75in",
                    "right": "0.75in",
                    "bottom": "0.75in",
                    "left": "0.75in",
                },
                print_background=True,
            )
        finally:
            browser.close()


def parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_MD,
        help="Source markdown path (default: docs/TECHNICAL-REPORT.md)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: same name as source with .pdf extension)",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="CUTIEE Technical Report",
        help="PDF metadata title",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parseArgs(argv)
    sourceMd = args.source.resolve()
    outputPdf = args.output.resolve() if args.output else sourceMd.with_suffix(".pdf")
    if not sourceMd.exists():
        sys.stderr.write(f"missing source markdown: {sourceMd}\n")
        return 1
    outputPdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        htmlPath = Path(tmp.name)
    try:
        runPandocToHtml(sourceMd, htmlPath, args.title)
        renderHtmlToPdf(htmlPath, outputPdf)
    finally:
        htmlPath.unlink(missing_ok=True)
    relPath = outputPdf.relative_to(REPO_ROOT) if outputPdf.is_relative_to(REPO_ROOT) else outputPdf
    print(f"Wrote {relPath} ({outputPdf.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
