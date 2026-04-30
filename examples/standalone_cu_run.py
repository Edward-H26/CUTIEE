"""Minimal standalone Computer Use run.

Demonstrates that CUTIEE's `agent/` package works as a standalone
library — no Django, no Neo4j, no allauth required. Pip-install the
parent `cutiee` package (or vendor `agent/` directly) and you're done.

Usage:
    GEMINI_API_KEY=your-key uv run python examples/standalone_cu_run.py

Override the model with CUTIEE_CU_MODEL=gemini-3-flash-preview if you
want deterministic replay across Google Flash promotions.
"""

from __future__ import annotations

import asyncio
import os

from agent import (
    ApprovalGate,
    BrowserController,
    ComputerUseRunner,
    GeminiComputerUseClient,
)


async def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Set GEMINI_API_KEY in your env. Get one at https://aistudio.google.com.")

    runner = ComputerUseRunner(
        browser=BrowserController(),  # visible window by default
        client=GeminiComputerUseClient(),  # gemini-flash-latest
        approvalGate=ApprovalGate(),  # auto-approves below MEDIUM risk
        initialUrl="https://en.wikipedia.org",
        maxSteps=6,
    )

    state = await runner.run(
        userId="demo-user",
        taskId="wiki-jupiter-moons",
        taskDescription="Search Wikipedia for the four largest moons of Jupiter and click on the top result.",
    )

    print()
    print(f"Completed:        {state.isComplete}")
    print(f"Reason:           {state.completionReason}")
    print(f"Steps recorded:   {state.stepCount()}")
    print(f"Total cost (USD): ${state.totalCostUsd:.4f}")
    print()
    print("Step trace:")
    for step in state.history:
        if step.action is None:
            continue
        print(
            f"  [{step.index:>2}] {step.action.type.value:<14} "
            f"tier={step.action.tier} cost=${step.action.cost_usd:.4f} "
            f"ok={step.verificationOk}"
        )


if __name__ == "__main__":
    asyncio.run(main())
