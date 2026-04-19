"""Cost benchmark for CUTIEE.

Builds three synthetic 15-step trajectories and runs them through the
router with both production pricing (Gemini 3.1) and the local stack
(Qwen3.5 0.8B). Writes a CSV summary to data/benchmarks/cost_runs.csv.

Usage:
    uv run python scripts/benchmark_costs.py --scenario all
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.routing.models.gemini_cloud import PRICING_PER_MILLION

OUTPUT_DIR = Path("data/benchmarks")
OUTPUT_FILE = OUTPUT_DIR / "cost_runs.csv"


@dataclass
class Scenario:
    name: str
    steps: int
    tierMix: dict[int, int]
    inputTokensPerStep: int = 4000
    outputTokensPerStep: int = 60


SCENARIOS: dict[str, Scenario] = {
    "naive_cloud": Scenario(name = "naive_cloud", steps = 15, tierMix = {3: 15}),
    "cutiee_first_run": Scenario(
        name = "cutiee_first_run", steps = 15, tierMix = {1: 11, 2: 3, 3: 1}
    ),
    "cutiee_replay": Scenario(name = "cutiee_replay", steps = 15, tierMix = {0: 15}),
    "cutiee_replay_with_mutation": Scenario(
        name = "cutiee_replay_with_mutation", steps = 15, tierMix = {0: 14, 2: 1}
    ),
}

TIER_MODEL_PRODUCTION = {
    0: ("replay", 0.0, 0.0),
    1: ("gemini-3.1-flash-lite", *PRICING_PER_MILLION["gemini-3.1-flash-lite"]),
    2: ("gemini-3.1-flash", *PRICING_PER_MILLION["gemini-3.1-flash"]),
    3: ("gemini-3.1-pro", *PRICING_PER_MILLION["gemini-3.1-pro"]),
}


def estimateScenarioCost(scenario: Scenario, *, environment: str) -> float:
    if environment == "local":
        return 0.0
    total = 0.0
    for tier, count in scenario.tierMix.items():
        if tier == 0:
            continue
        _, inPrice, outPrice = TIER_MODEL_PRODUCTION[tier]
        inputCost = scenario.inputTokensPerStep * count / 1_000_000 * inPrice
        outputCost = scenario.outputTokensPerStep * count / 1_000_000 * outPrice
        total += inputCost + outputCost
    return round(total, 6)


def runBenchmarks(scenarios: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    chosen = scenarios if scenarios != ["all"] else list(SCENARIOS.keys())
    for name in chosen:
        if name not in SCENARIOS:
            print(f"warning: unknown scenario {name!r}, skipping", file = sys.stderr)
            continue
        scenario = SCENARIOS[name]
        productionCost = estimateScenarioCost(scenario, environment = "production")
        localCost = estimateScenarioCost(scenario, environment = "local")
        rows.append(
            {
                "scenario": name,
                "steps": scenario.steps,
                "tier_mix": str(scenario.tierMix),
                "production_cost_usd": productionCost,
                "local_cost_usd": localCost,
            }
        )
    return rows


def writeCsv(rows: list[dict[str, object]]) -> None:
    OUTPUT_DIR.mkdir(parents = True, exist_ok = True)
    with OUTPUT_FILE.open("w", newline = "", encoding = "utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames = ["scenario", "steps", "tier_mix", "production_cost_usd", "local_cost_usd"],
        )
        writer.writeheader()
        writer.writerows(rows)


def printSummary(rows: list[dict[str, object]]) -> None:
    width = max(len(str(row["scenario"])) for row in rows) + 2
    header = f"{'scenario'.ljust(width)} {'steps':>6} {'production':>12} {'local':>10}"
    print(header)
    print("-" * len(header))
    for row in rows:
        scenario = str(row["scenario"]).ljust(width)
        steps = f"{row['steps']:>6}"
        production = f"${float(row['production_cost_usd']):>10.4f}"
        local = f"${float(row['local_cost_usd']):>8.4f}"
        print(f"{scenario} {steps} {production} {local}")


def main() -> int:
    parser = argparse.ArgumentParser(description = "Run CUTIEE cost benchmarks")
    parser.add_argument(
        "--scenario",
        nargs = "+",
        default = ["all"],
        help = f"Scenario(s) to run, or 'all' (default). Options: {', '.join(SCENARIOS)}",
    )
    args = parser.parse_args()
    rows = runBenchmarks(args.scenario)
    if not rows:
        print("No scenarios to run.", file = sys.stderr)
        return 1
    writeCsv(rows)
    printSummary(rows)
    print(f"\nWrote {len(rows)} rows to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
