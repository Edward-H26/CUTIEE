"""Cost benchmark for CUTIEE.

Builds synthetic 15-step trajectories and estimates Gemini CU, API-only,
replay, and local memory-side pricing.
Writes a CSV summary to data/benchmarks/cost_waterfall.csv.

Usage:
    uv run python scripts/benchmark_costs.py --scenario all
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.routing.models.gemini_cu import CU_PRICING

OUTPUT_DIR = Path("data/benchmarks")
OUTPUT_FILE = OUTPUT_DIR / "cost_waterfall.csv"


@dataclass
class Scenario:
    name: str
    steps: int
    tierMix: dict[int, int]
    inputTokensPerStep: int = 4000
    outputTokensPerStep: int = 60


SCENARIOS: dict[str, Scenario] = {
    "api_only_anthropic_cu": Scenario(name="api_only_anthropic_cu", steps=15, tierMix={4: 15}),
    "naive_cloud": Scenario(name="naive_cloud", steps=15, tierMix={3: 15}),
    "cutiee_first_run": Scenario(name="cutiee_first_run", steps=15, tierMix={1: 11, 2: 3, 3: 1}),
    "cutiee_replay": Scenario(name="cutiee_replay", steps=15, tierMix={0: 15}),
    "cutiee_replay_with_mutation": Scenario(
        name="cutiee_replay_with_mutation", steps=15, tierMix={0: 14, 2: 1}
    ),
}

# Production tier models with pricing (in/out per 1M tokens)
TIER_MODEL_PRODUCTION = {
    0: ("replay", 0.0, 0.0),
    1: ("gemini-flash-latest", *CU_PRICING["gemini-flash-latest"]),
    2: ("gemini-3-flash-preview", *CU_PRICING["gemini-3-flash-preview"]),
    3: ("gemini-3-flash-preview", *CU_PRICING["gemini-3-flash-preview"]),
    4: ("anthropic-computer-use-api-only", 3.0, 15.0),
}

# Projected local memory-side and replay models from the paper.
#
# Tier 1 `qwen3-0.8b-local` is now SHIPPING for memory-side reflection
# and decomposition (see `agent/memory/local_llm.py`); the CU loop is
# still Gemini-only, so this projection only applies if Qwen ever gates
# the screenshot-control loop too. Tiers 2-3 remain projections from
# the paper.
TIER_MODEL_PROJECTED = {
    0: ("replay", 0.0, 0.0),
    1: ("qwen3-0.8b-local", 0.0, 0.0),  # SHIPPING for memory-side LLM; projected for CU loop
    2: ("fara-7b-4bit", 0.003, 0.003),  # projected, ~$0.003/call
    3: ("gemini-flash", 0.15, 0.60),  # from paper
    4: ("anthropic-computer-use-api-only", 3.0, 15.0),
}


def estimateScenarioCost(
    scenario: Scenario, *, tier_models: dict[int, tuple[str, float, float]]
) -> float:
    total = 0.0
    for tier, count in scenario.tierMix.items():
        if tier == 0:
            continue
        _, inPrice, outPrice = tier_models[tier]
        inputCost = scenario.inputTokensPerStep * count / 1_000_000 * inPrice
        outputCost = scenario.outputTokensPerStep * count / 1_000_000 * outPrice
        total += inputCost + outputCost
    return round(total, 6)


def runBenchmarks(scenarios: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    chosen = scenarios if scenarios != ["all"] else list(SCENARIOS.keys())
    for name in chosen:
        if name not in SCENARIOS:
            print(f"warning: unknown scenario {name!r}, skipping", file=sys.stderr)
            continue
        scenario = SCENARIOS[name]
        productionCost = estimateScenarioCost(scenario, tier_models=TIER_MODEL_PRODUCTION)
        projectedCost = estimateScenarioCost(scenario, tier_models=TIER_MODEL_PROJECTED)

        apiOnlyCost = estimateScenarioCost(
            SCENARIOS["api_only_anthropic_cu"], tier_models=TIER_MODEL_PRODUCTION
        )
        savingsVsApiOnly = (
            ((apiOnlyCost - productionCost) / apiOnlyCost * 100) if apiOnlyCost > 0 else 0.0
        )

        rows.append(
            {
                "scenario": name,
                "step_count": scenario.steps,
                "tier_mix": str(scenario.tierMix),
                "production_cost_usd": productionCost,
                "projected_local_replay_cost_usd": projectedCost,
                "savings_vs_api_only_pct": round(savingsVsApiOnly, 2),
            }
        )
    return rows


def writeCsv(rows: list[dict[str, object]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario",
                "step_count",
                "tier_mix",
                "production_cost_usd",
                "projected_local_replay_cost_usd",
                "savings_vs_api_only_pct",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def printSummary(rows: list[dict[str, object]]) -> None:
    width = max(len(str(row["scenario"])) for row in rows) + 2
    header = f"{'scenario'.ljust(width)} {'steps':>6} {'production':>12} {'projected':>12} {'savings':>10}"
    print(header)
    print("-" * len(header))
    for row in rows:
        scenario = str(row["scenario"]).ljust(width)
        steps = f"{row['step_count']:>6}"
        production = f"${float(row['production_cost_usd']):>10.4f}"
        projected = f"${float(row['projected_local_replay_cost_usd']):>10.4f}"
        savings = f"{float(row['savings_vs_api_only_pct']):>8.1f}%"
        print(f"{scenario} {steps} {production} {projected} {savings}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CUTIEE cost benchmarks")
    parser.add_argument(
        "--scenario",
        nargs="+",
        default=["all"],
        help=f"Scenario(s) to run, or 'all' (default). Options: {', '.join(SCENARIOS)}",
    )
    args = parser.parse_args()
    rows = runBenchmarks(args.scenario)
    if not rows:
        print("No scenarios to run.", file=sys.stderr)
        return 1
    writeCsv(rows)
    printSummary(rows)
    print(f"\nWrote {len(rows)} rows to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
