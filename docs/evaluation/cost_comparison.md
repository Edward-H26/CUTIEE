# Part 4.4 — Cost and resource comparison

## Pricing reference

CUTIEE defaults to **screenshot-based Computer Use everywhere** as of
2026-04. The default model is `gemini-flash-latest` because Google
extended the `ComputerUse` tool to the regular Flash family at flash
pricing, eliminating the cost penalty that previously made CU a
"specialty" tier. The DOM router stays available as an opt-in escape
hatch (`?use_cu=0`) for high-volume DOM-stable workflows.

### Computer Use (default)

| Model | Input $/MT | Output $/MT | Notes |
|-------|------------|-------------|-------|
| **gemini-flash-latest** | **0.15** | **0.60** | Default. Tracks Google's latest Flash. |
| gemini-3-flash-preview | 0.15 | 0.60 | Pinned alternative for deterministic replay. |
| gemini-2.5-computer-use-preview-10-2025 | 1.25 | 5.00 | Specialty preview, ~8× more expensive. Opt-in via `CUTIEE_CU_MODEL`. |

### DOM router (opt-in via `?use_cu=0`)

Pro variants are intentionally disabled at the client level (rejected by
`GeminiCloudClient.__post_init__`) so the worst case DOM-router escalation
stays bounded at flash pricing.

| Tier | Model | Input $/MT | Output $/MT |
|------|-------|------------|-------------|
| 1 | gemini-3.1-flash-lite-preview | 0.075 | 0.30 |
| 2 | gemini-3-flash-preview | 0.15 | 0.60 |
| 3 | gemini-3-flash-preview | 0.15 | 0.60 |

Local Qwen3.5 0.8B is treated as zero marginal cost.

## Per-task cost

The numbers below come from `scripts/benchmark_costs.py`, which composes
synthetic 15-step trajectories and runs them through the router with
both production pricing and the local stack.

| Scenario | Steps | Tier mix | Production cost | Local cost |
|----------|-------|----------|-----------------|------------|
| Naive cloud-only baseline | 15 | T3 x 15 | $0.300 | n/a |
| CUTIEE first run, novel | 15 | T1 x 11, T2 x 3, T3 x 1 | $0.0210 | $0.000 |
| CUTIEE replay, identical task | 15 | replay only | $0.000 | $0.000 |
| CUTIEE replay with one mutation | 15 | replay 14 + T2 x 1 | $0.0009 | $0.000 |

For a typical user mix of 80% recurring and 20% novel tasks the weighted
production cost lands around $0.004 per task, roughly 1.3% of the cloud
baseline.

## Lifecycle effect

| Month | Novel % | Replay % | Avg cost / task |
|-------|---------|----------|-----------------|
| 1 | 100 | 0 | $0.05 |
| 3 | 20 | 80 | $0.01 |
| 6 | 10 | 90 | $0.005 |
| 12 | 5 | 95 | $0.003 |

The flywheel strengthens as the bullet store grows; the asymptote sits
at roughly $0.003 per task because some fraction of work always hits
genuine novelty.

## Resource footprint

- Local: Qwen3.5 0.8B Q4_K_M GGUF requires about 600 MB of disk and
  roughly 2 GB of RAM at runtime. Inference latency on a CPU laptop
  is about 2 seconds per Tier-1 call.
- Production: Render starter dyno (512 MB RAM, 0.5 CPU) is sufficient
  for the web tier when browser automation is offloaded. AuraDB Free
  provides up to 200,000 nodes and 400,000 relationships, which holds
  the INFO490 workload several thousand task executions deep.

## Reproduction

```bash
uv run python scripts/benchmark_costs.py --scenario all
```

The script writes a CSV to `data/benchmarks/cost_runs.csv` and prints a
summary table. CI runs it on every push so cost regressions surface in
review.
