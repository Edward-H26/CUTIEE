"""Start all three demo Flask sites (spreadsheet, slides, form) in subprocesses.

Usage:

    uv run python scripts/start_demo_sites.py

Stops cleanly on SIGINT.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

SITES: list[tuple[str, int]] = [
    ("demo_sites.spreadsheet_site.app", 5001),
    ("demo_sites.slides_site.app", 5002),
    ("demo_sites.form_site.app", 5003),
]


def main() -> int:
    repoRoot = Path(__file__).resolve().parent.parent
    procs: list[subprocess.Popen[bytes]] = []
    for module, port in SITES:
        cmd = [sys.executable, "-c", f"import {module} as m; m.createApp().run(host='127.0.0.1', port={port})"]
        proc = subprocess.Popen(cmd, cwd = str(repoRoot))
        procs.append(proc)

    def _shutdown(_signum: int, _frame: object) -> None:
        for proc in procs:
            proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(2)
        for proc in procs:
            if proc.poll() is not None:
                _shutdown(0, None)


if __name__ == "__main__":
    sys.exit(main())
