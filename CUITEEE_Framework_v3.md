# CUITEEE

## Computer Use agentIc-framework with Token Efficient harnEss Engineering

### A Framework for Cost-Viable Computer Use Agents Through Three Core Mechanisms

---

**Date:** April 16, 2026  
**Version:** 3.0  
**Core Mechanisms:** Procedural Memory Replay · Temporal Recency Pruning · Multi-Model Routing

---

## 1. Framework Identity

**CUITEEE** = **C**omputer **U**se agent**I**c-framework with **T**oken **E**fficient harn**E**ss **E**ngineering

The name carries the full meaning of the system:

- **Computer Use** — the domain (GUI-controlling AI agents)
- **agentIc-framework** — the structure (a framework for building agents, not a single model)
- **Token Efficient** — the objective (minimize token consumption per task)
- **harnEss Engineering** — the method (engineered infrastructure around any CUA model)

CUITEEE is an **agentic framework** — a reusable harness that wraps around any underlying CUA model (Fara-7B, UI-TARS, Claude, GPT, Gemini) and makes that model dramatically cheaper to operate through three engineered mechanisms.

---

## 2. The Three Core Mechanisms

### Mechanism 1: Procedural Memory Replay (100% cost reduction for recurring tasks)

After the agent successfully completes a task, it distills the workflow into a compact replayable template. Subsequent executions of the same task replay the template directly through the browser automation layer — **zero VLM inference is required**.

A 6-step bill payment workflow stores as a ~100-token template. A naive CUA would re-encode 6 screenshots (24,000+ visual tokens) and re-reason through the entire workflow. The savings are absolute: recurring tasks drop to $0.00.

**Key properties:**
- Templates store parameterized action sequences with verification conditions
- Matching uses cosine similarity on task embeddings (threshold: 0.85)
- Self-healing: if a step fails verification, fall through to the VLM for re-grounding, patch the template, continue
- High-risk steps retain explicit user approval requirements

### Mechanism 2: Temporal Recency Pruning (60–80% context reduction)

Research published in March 2026 (Li et al., arXiv:2603.26041) demonstrates that GUI agents exhibit a **recency effect identical to human cognition** — current decisions depend primarily on the 2–3 most recent observations. CUITEEE operationalizes this finding:

- **Recent N=3 steps**: Full-resolution screenshots/DOM (12,000 tokens)
- **Middle 3 steps**: Action text only, no screenshots (~100 tokens)
- **Distant history**: One-line summary (~30 tokens)

A 15-step task drops from 60,750 tokens (naive) to 12,780 tokens (pruned) — a **79% reduction**. A 30-step task saves 89%. Context stays nearly flat regardless of task length, which is critical for long-horizon workflows.

**Foreground-background decomposition**: The same research shows that background regions in screenshots capture interface-state transitions. CUITEEE allocates graduated token budgets: 70% foreground / 30% background for the most recent screenshot, shifting to 50/50 for the third-most-recent.

### Mechanism 3: Multi-Model Routing (70–78% inference cost reduction)

Not all GUI actions require the same computational power. The AVR framework (Liu et al., March 2026) demonstrates that routing each action to the cheapest viable model achieves 78% cost reduction while staying within 2 percentage points of an all-large-model baseline.

**CUITEEE model tiers:**

| Tier | Model | Cost | Use Case |
|------|-------|------|----------|
| 1 (Edge) | ShowUI 2B / Qwen2.5-VL-3B | ~$0.00 (local CPU) | Login forms, known buttons, text fields |
| 2 (Local) | Fara-7B Q4 | ~$0.003/call (local GPU) | Navigation, form filling, medium UIs |
| 3 (Cloud) | Claude Sonnet / OpenAI CUA | ~$0.02/call | Novel UIs, complex reasoning, high-risk |

A 120M-parameter difficulty classifier estimates action complexity, routes to the appropriate tier, and escalates via logprob confidence probing when needed.

---

## 3. Compound Cost Savings

The three mechanisms compound multiplicatively:

```
Novel task (no template): $0.30 (naive) × 0.25 (pruning) × 0.28 (routing) = $0.021
Recurring task:            $0.30 × 0.00 (replay) = $0.000
```

For a typical user mix (80% recurring, 20% novel):

```
Weighted avg = 0.80 × $0.000 + 0.20 × $0.021 = $0.004 per task
```

Compare to cloud-only baseline ($0.30/task): **98.7% cost reduction**.

---

## 4. Lifecycle Economics

The flywheel strengthens over time as procedural memory accumulates:

| Month | Novel % | Replay % | Avg Cost/Task |
|-------|---------|----------|---------------|
| 1 | 100% | 0% | $0.05 |
| 3 | 20% | 80% | $0.01 |
| 6 | 10% | 90% | $0.005 |
| 12 | 5% | 95% | $0.003 |

This economic profile makes $9.99/month consumer subscriptions viable at 95%+ gross margins — something no prior CUA architecture achieves.

---

*See companion document `CUITEEE_Claude_Code_Implementation.md` for the complete Claude Code build guide.*
