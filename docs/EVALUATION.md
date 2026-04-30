# CUTIEE Evaluation

System evaluation per INFO490 A10 rubric Part 4.1. Five+ realistic test cases with
Input / Expected Behavior / Actual Output / Quality / Latency columns.

This revision prefers repo-local evidence generated on April 29, 2026:

- `data/eval/20260429-summary.md`
- `data/eval/20260429-backend-comparison.csv`
- `data/benchmarks/cost_waterfall.csv`

---

## Test Cases

| # | Input (task description) | Initial URL | Expected behavior | Actual output | Quality (0-5) | Latency |
|---|---|---|---|---|---|---|
| 1 | "Open the demo spreadsheet and locate row 17" | `http://localhost:5001/` | Reach the spreadsheet target and finish the scripted demo cleanly | **Actual:** success, 3 steps, $0 in local/mock mode. The historical rows requested `gemini` and `browser_use`, but because `CUTIEE_ENV=local`, they exercised the mock CU harness rather than live CU backends. | 5 / 5 for harness flow, not a live backend quality score | 2.55 s and 1.56 s in local/mock mode |
| 2 | "Complete page 1 of the form wizard with sample data" | `http://localhost:5003/` | Fill the wizard inputs and advance without error | **Actual:** success, 3 steps, $0 in local/mock mode. Treat the backend labels in `data/eval/20260429-summary.md` as requested backend labels, not proof of live Gemini or browser-use execution. | 4 / 5 for harness flow, not a live backend quality score | 2.35 s and 1.14 s in local/mock mode |
| 3 | "Advance through five slides in the slide deck" | `http://localhost:5002/` | Navigate the slide demo and complete the scripted endpoint condition | **Actual:** success, 3 steps, $0 in local/mock mode. Live CU evaluation requires `CUTIEE_ENV=production` or `CUTIEE_LOCAL_USE_GEMINI=true`. | 5 / 5 for harness flow, not a live backend quality score | 1.58 s and 0.80 s in local/mock mode |
| 4 | "Novel first-run cost mix" | n/a (cost benchmark) | Show that CUTIEE's first-run tier mix is cheaper than a fully hosted API-only Computer Use baseline | **Actual:** `api_only_anthropic_cu` records `$0.1935`, `naive_cloud` records the Gemini all-cloud comparison at `$0.00954`, and `cutiee_first_run` records `$0.000673` projected replay plus local-memory-side cost (`data/benchmarks/cost_waterfall.csv`) | 4 / 5 | <1 s script runtime |
| 5 | "Replay scenario: identical task twice in a row" | n/a (cost benchmark) | Show that cached procedural replay collapses repeated-task inference cost to zero | **Actual:** `cutiee_replay` benchmark row records 15 replayed steps and `$0.0000` cost with 100.0% savings vs the API-only baseline; `cutiee_replay_with_mutation` retains 99.67% savings with one non-replayed Gemini step (`data/benchmarks/cost_waterfall.csv`) | 5 / 5 | <1 s script runtime |
| 6 | "Reflect on a completed localhost run" | `http://localhost:5001/` | `Qwen/Qwen3.5-0.8B` emits at least one procedural lesson with the expected JSON schema | **Actual unit-test evidence:** `tests/agent/test_local_llm.py:62 test_reflector_prefers_local_qwen_for_localhost` proves the path activates and produces a `procedural` lesson with the `localhost` tag. | 4 / 5 | ~2 s on M-series MPS, ~5 s on CPU; first call adds ~10 s warmup |
| 7 | "Pathological 50-step task that would otherwise exceed the per-task cost cap" | any production URL | The per-task cost guard fires at `CUTIEE_MAX_COST_USD_PER_TASK=0.50`, the runner aborts gracefully with `completion_reason="cost_cap_reached:per_task"`, the partial audit trail persists, and the next known over-budget model call is skipped | **Actual:** `agent/harness/computer_use_loop.py:_checkCostPreflight` runs before `nextAction()` and uses the client step-cost estimate to stop known over-budget calls. `tests/agent/test_computer_use_runner.py::test_cost_cap_preflight_stops_before_model_call` verifies zero model calls on a preflight cap hit. The Neo4j hourly and daily ledger still performs the post-call atomic accounting in `agent/harness/cost_ledger.py:incrementAndCheck`. | 4 / 5 | projected ~25 s wall-clock on a 15-step run, unit test is sub-second |
| 8 | "Re-run a task whose cached procedural template no longer matches the live page" | the same URL the template was learned against | Phase 17 plan-drift handler at `agent/harness/computer_use_loop.py:_handlePlanDrift` detects the URL divergence on a replay step, blocks the run, and asks the user to approve or cancel via the HTMX modal. If the user cancels, the audit trail records `completion_reason="plan_drift_cancelled"`; if the user approves, the runner falls through to a fresh model call rather than executing stale coordinates. | **Actual:** verified by `tests/agent/test_computer_use_runner.py::test_plan_drift_cancelled_before_stale_fragment_executes` and documented at `SPEC.md:136-138`. The drift hook never executes a stale fragment without user confirmation. | 5 / 5 (the safety mechanism behaves exactly as designed) | projected ~3 s to detect the drift plus user-decision wall-clock, unit test is sub-second |

---

## Crossover Analysis

Section 5.2 of the technical report identifies the break-even region between CUTIEE's
fixed hosting cost and Anthropic CU's purely variable spend. The crossover point where
CUTIEE becomes more expensive than Anthropic CU sits below approximately 10 paid task
runs per day per Render dyno. Above roughly 100 task runs per day total, the CUTIEE
design pulls ahead and the gap widens linearly with run count.

| Daily paid task volume | Break-even interpretation |
|---|---|
| Below approximately 10 paid runs/day per Render dyno | Anthropic CU's flat per-use economics are cheaper because Render's fixed hosting cost dominates the bill. |
| Above roughly 100 paid runs/day total | CUTIEE becomes cheaper overall, and the savings widen linearly as run count increases. |

---

## Cross-reference: memory-architecture evaluation (external)

CUTIEE inherits the ACE memory architecture validated in the v5 benchmark. The numbers
below are external context for why replay-heavy tasks matter so much, but they are no
longer the only support for rows 4 and 5 above because those rows now cite repo-local
benchmark output.

| Metric (CL-bench, n=200) | Baseline (no ACE) | ACE-augmented | Delta |
|---|---|---|---|
| Overall solving rate | 19.5% | 23.0% | **+17.9%** relative |
| Procedural task execution (n=47) | 14.9% | 25.5% | **+71.4%** relative |
| Rule system application (n=62) | 25.8% | 33.9% | **+31.2%** relative |
| Domain knowledge reasoning (n=85) | 17.6% | 14.1% | -20.0% (the one regression) |
| Avg tokens / task | 11,045 | 44,516 | +303% |
| Avg latency (ms) | 36,735 | 130,008 | +254% |
| p50 latency (ms) | 28,328 | 74,550 | +163% |
| p95 latency (ms) | 96,838 | 480,594 | +396% |
| Estimated cost | $6.84 | $26.85 (+$122.79 auxiliary = $169.32 total) | +12x |

**Source:** `https://github.com/Edward-H26/LongTermMemoryBased-ACE/blob/main/benchmark/results/v5/comparison_report_v5.md`

CUTIEE's value-add over vanilla v5 ACE is the cost-mitigation layer that closes the +12x
penalty:

- **Procedural replay tier** sets cost to $0 on cached recurring tasks (rows 5 above)
- **Local Qwen3.5-0.8B for the auxiliary reflector / decomposer path** eliminates the
  +$122.79 auxiliary cost component for localhost demos (row 6)
- **Procedural replay plus Gemini Flash pricing** reduces recurring-task cost to zero
  and keeps novel-task cost below the API-only baseline (`scripts/benchmark_costs.py`)

---

## Crossover analysis (cost vs API-only baseline)

The rubric's Part 4.4 asks when each system is cheaper. The summary lives here so the
grader does not need to cross-reference `docs/TECHNICAL-REPORT.md` Section 5.2. The
underlying derivation is reproduced verbatim from that section so both documents stay
in sync.

> **Relevant paragraph from TECHNICAL-REPORT.md Section 5.2:**
> Anthropic CU's 25x per-step price multiplier becomes a 40 to 50x difference on
> day-to-day cost at 10k DAU because procedural replay drives a portion of CUTIEE's
> calls to zero. The crossover point where CUTIEE becomes more expensive than Anthropic
> CU sits below approximately 10 paid task runs per day per Render dyno: at that scale
> Render's fixed cost dominates the bill for both designs and the Anthropic flat rate
> wins on simplicity. Above roughly 100 task runs per day total, the CUTIEE design
> pulls ahead and the gap widens linearly with run count.

The break-even reduces to a two-row table:

| Daily task volume | Cheaper system | Why |
|---|---|---|
| Below ~10 paid task runs per day per Render dyno | **API-only baseline** (Anthropic CU) | Render's fixed monthly cost (~$50 web + ~$25 worker = ~$75) dominates the bill at this scale; the variable API cost is small compared to infrastructure, and the API-only design has no infrastructure of its own to maintain |
| Above ~100 paid task runs per day total | **CUTIEE** | API savings at the per-step level (20x cheaper Gemini Flash CU plus zero-cost replay tier on recurring tasks) overcome Render's fixed cost; the gap widens linearly with run volume and reaches the 21x cohort margin documented at `docs/TECHNICAL-REPORT.md` Section 5.2 by the time daily volume exceeds 250 tasks (50 users * 5 tasks per user) |

CUTIEE's target cohort runs roughly 250 tasks per day, which is approximately 30x the
break-even threshold. The full sensitivity-analysis derivation (with the formula
`cutiee_cost(n, r) = n * (1 - r) * $0.0046 + n * $0.001` and the $50-per-month Render
break-even floor of ~9 tasks per day) lives at `README_AI.md` "Sensitivity analysis:
where does the design break even?" subsection.

---

## Reproduction

```bash
# Start demo Flask sites in one terminal
uv run python scripts/start_demo_sites.py

# Pre-cache Qwen weights once for row 6 to load in <2 s
uv run python scripts/cache_local_qwen.py

# In a second terminal, run the eval harness in local/mock mode
CUTIEE_ENV=local CUTIEE_USE_STUB_BROWSER=true \
  uv run python -m agent.eval.webvoyager_lite --backend gemini --backend browser_use

# Run the local-LLM unit tests (covers row 6 reflector path activation)
uv run pytest tests/agent/test_local_llm.py -v

# Run the cost benchmark (covers rows 4-5)
uv run python scripts/benchmark_costs.py --scenario all
```

Output files land under `data/eval/<YYYYMMDD>-backend-comparison.csv` and
`data/eval/<YYYYMMDD>-summary.md`.

---

## Quality scoring methodology

The Quality column uses a 0-5 rubric that scores both task completion and the
intermediate trajectory:

- **5:** Task completes; every intermediate step is reasonable; no unnecessary actions;
  cost is minimal for the achieved outcome.
- **4:** Task completes; minor inefficiencies (e.g., redundant click, unnecessary
  scroll) that do not affect outcome.
- **3:** Task completes after retries OR requires a non-trivial fallback (e.g., Gemini
  takes over from Qwen mid-flight).
- **2:** Task partially completes; some sub-goals missed.
- **1:** Task does not complete; runner exits with a non-`complete` reason.
- **0:** Runner crashes or hangs.

Latency is wall-clock from `run_task_view` POST to the runner's final
`progressCallback` write; it includes browser navigation, model inference, Neo4j
round-trips, and the screenshot store TTL bookkeeping.
