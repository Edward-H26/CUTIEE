"""Phase 2 lightweight evaluation harness.

Runs a fixed set of scripted tasks against both CU backends (Gemini
native and browser-use with Gemini 3 Flash) and reports success rate,
per-task cost, and per-task step count. Default target is the
`demo_sites/` Flask apps bundled with CUTIEE. A `--live` flag plus
`CUTIEE_EVAL_LIVE=1` unlocks runs against real sites, which we
recommend only during evaluation windows because of the cost exposure
and risk surface.

Outputs:
  * `data/eval/<date>-backend-comparison.csv` with one row per
    (task, backend) run.
  * A one-page markdown summary at `data/eval/<date>-summary.md`.

The harness calls `apps.tasks.services.runTaskForUser` directly. That
function is synchronous (it wraps `asyncio.run` internally), accepts
`description` and `taskId`, and returns a `TaskRunSummary` with
`stepCount`, `totalCostUsd`, `completed`, and `completionReason`.

Requirements for a meaningful run:
  * Neo4j reachable (bolt url in .env).
  * `CUTIEE_ENV=production` for real model calls, or `local` for
    scripted mock actions (fast, deterministic, no spend).
  * Set `CUTIEE_USE_STUB_BROWSER=0` only when a Playwright Chromium
    is installed; otherwise the stub browser is used and tasks
    still complete but only exercise the harness plumbing.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.harness.completion import completionReasonSucceeded

_logger = logging.getLogger(__name__)


@dataclass
class EvalTask:
    name: str
    description: str
    startUrl: str
    expectedFinish: str = ""


@dataclass
class EvalResult:
    task: str
    backend: str
    success: bool
    steps: int
    costUsd: float
    completionReason: str = ""
    notes: str = ""


DEFAULT_TASKS: list[EvalTask] = [
    EvalTask(
        name="open_spreadsheet",
        description="Open the demo spreadsheet and locate row 17.",
        startUrl="http://localhost:5001/",
        expectedFinish="row_found",
    ),
    EvalTask(
        name="fill_form_wizard",
        description="Complete page 1 of the form wizard with sample data.",
        startUrl="http://localhost:5003/",
        expectedFinish="page_submitted",
    ),
    EvalTask(
        name="navigate_slides",
        description="Advance through five slides in the slide deck.",
        startUrl="http://localhost:5002/",
        expectedFinish="final_slide",
    ),
]


def runSingle(task: EvalTask, backend: str, verbose: bool = False) -> EvalResult:
    """Run one scripted task on one backend and return metrics.

    `runTaskForUser` is synchronous, so we call it directly. Any
    exception gets surfaced in `notes` with a traceback tail so the
    operator can debug without re-running.
    """
    os.environ["CUTIEE_CU_BACKEND"] = backend
    # The harness deliberately forces local mode unless the operator
    # has already set CUTIEE_ENV=production. Production + live Gemini
    # incurs real cost and should be opt-in.
    os.environ.setdefault("CUTIEE_ENV", "local")
    effectiveBackend = _effectiveBackendLabel(backend)
    from apps.tasks import repo as tasksRepo
    from apps.tasks import services

    started = datetime.now(timezone.utc)
    # The services layer expects the :Task node to exist already (the
    # view creates it before calling runTaskForUser). The harness
    # mimics that contract so real audit, memory, and progress paths
    # exercise identically to a user-submitted run.
    taskRow = tasksRepo.createTask(
        userId="eval-harness",
        description=task.description,
        initialUrl=task.startUrl,
    )
    # Compatible with both dataclass and dict returns from createTask.
    taskId = (
        taskRow["id"]
        if isinstance(taskRow, dict)
        else getattr(taskRow, "id", getattr(taskRow, "task_id", None))
    )
    if not taskId:
        raise RuntimeError(f"createTask returned unrecognized shape: {taskRow!r}")
    try:
        summary = services.runTaskForUser(
            userId="eval-harness",
            taskId=taskId,
            description=task.description,
            initialUrl=task.startUrl,
        )
        finished = datetime.now(timezone.utc)
        notes = f"elapsed={(finished - started).total_seconds():.2f}s execution={summary.executionId[:8]}"
        if effectiveBackend != backend:
            notes = f"{notes} requested_backend={backend}"
        return EvalResult(
            task=task.name,
            backend=effectiveBackend,
            success=bool(summary.completed and completionReasonSucceeded(summary.completionReason)),
            steps=summary.stepCount,
            costUsd=summary.totalCostUsd,
            completionReason=summary.completionReason,
            notes=notes,
        )
    except Exception as exc:
        tail = traceback.format_exc().splitlines()[-3:]
        if verbose:
            _logger.exception("eval task %s failed on backend %s", task.name, backend)
        return EvalResult(
            task=task.name,
            backend=effectiveBackend,
            success=False,
            steps=0,
            costUsd=0.0,
            completionReason="eval_error",
            notes=f"{exc!r} | {' | '.join(tail)}",
        )


def _effectiveBackendLabel(requestedBackend: str) -> str:
    cutieeEnv = os.environ.get("CUTIEE_ENV", "")
    localUsesGemini = cutieeEnv == "local" and os.environ.get(
        "CUTIEE_LOCAL_USE_GEMINI", "false"
    ).lower() in {"1", "true", "yes"}
    if cutieeEnv == "production" or localUsesGemini:
        return requestedBackend
    return "mock"


def writeOutputs(results: list[EvalResult], outDir: Path) -> Path:
    outDir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    csvPath = outDir / f"{stamp}-backend-comparison.csv"
    with csvPath.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(asdict(EvalResult("", "", False, 0, 0.0)).keys())
        )
        writer.writeheader()
        for row in results:
            writer.writerow(asdict(row))

    mdPath = outDir / f"{stamp}-summary.md"
    with mdPath.open("w") as fh:
        fh.write(f"# CUTIEE Backend Eval {stamp}\n\n")
        for backend in sorted({r.backend for r in results}):
            subset = [r for r in results if r.backend == backend]
            successes = sum(1 for r in subset if r.success)
            avgCost = sum(r.costUsd for r in subset) / max(1, len(subset))
            avgSteps = sum(r.steps for r in subset) / max(1, len(subset))
            fh.write(
                f"## Backend: `{backend}`\n\n"
                f"- Success rate: {successes}/{len(subset)}\n"
                f"- Average cost per task: ${avgCost:.4f}\n"
                f"- Average step count: {avgSteps:.1f}\n\n"
            )
            for row in subset:
                fh.write(
                    f"- `{row.task}` ok={row.success} steps={row.steps} "
                    f"cost=${row.costUsd:.4f} reason={row.completionReason or '-'}\n"
                )
            fh.write("\n")
    return csvPath


def runSuite(backends: list[str], tasks: list[EvalTask], verbose: bool) -> list[EvalResult]:
    out: list[EvalResult] = []
    for backend in backends:
        for task in tasks:
            out.append(runSingle(task, backend, verbose=verbose))
    return out


def parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="webvoyager_lite")
    parser.add_argument(
        "--backend",
        action="append",
        choices=["gemini", "browser_use"],
        default=[],
        help="CU backend to exercise. Pass more than once to run multiple.",
    )
    parser.add_argument(
        "--out",
        default="data/eval",
        help="Output directory for the CSV and markdown summary.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Unlock real-site runs. Requires CUTIEE_EVAL_LIVE=1.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print tracebacks for each failing task to stderr.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parseArgs(argv)
    backends = args.backend or ["gemini"]
    if args.live and os.environ.get("CUTIEE_EVAL_LIVE") != "1":
        _logger.error("--live requires CUTIEE_EVAL_LIVE=1; aborting.")
        return 2

    results = runSuite(backends, DEFAULT_TASKS, verbose=args.verbose)
    csvPath = writeOutputs(results, Path(args.out))
    _logger.info("")
    _logger.info(
        f"{'backend':14s} {'task':24s} {'ok':5s} {'steps':>5s} {'cost':>9s} {'reason':20s} notes"
    )
    _logger.info("-" * 100)
    for row in results:
        _logger.info(
            f"{row.backend:14s} {row.task:24s} "
            f"{str(row.success):5s} {row.steps:>5d} ${row.costUsd:>7.4f} "
            f"{row.completionReason[:19]:20s} {row.notes[:60]}"
        )
    _logger.info("")
    _logger.info("CSV: %s", csvPath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
