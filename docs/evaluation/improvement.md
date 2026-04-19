# Part 4.3 — Improvement case

## Before

Pre-CUTIEE the same workload would have used a single cloud model for
every step. A 15-step Sheets task on a frontier vision model burned
roughly 60,000 input tokens per call and ran 15 inferences, totalling
about 900,000 input tokens for one task. At Gemini 3.1 Flash pricing of
$0.15 per million input tokens this is roughly $0.135 in input cost
alone, plus output and image surcharges that push the total past $0.30.

A repeated run incurred the same cost. Workflow learning was nonexistent.

## After

CUTIEE runs the same 15-step task as follows:

- The router classifies most steps as easy and routes them to Tier 1.
  Only one or two steps escalate, typically to Tier 2.
- The pruner caps each model call at roughly 12,000 tokens by keeping
  only the recent N=3 DOM dumps and a deterministic rollup of the rest.
- The reflector emits one procedural bullet per successful step.
- The second identical run hits the replay path. The browser controller
  re-executes the bullet sequence in less than two seconds and the
  router never fires.

Per-task cost falls from about $0.30 on the cloud-only baseline to
roughly $0.004 on the CUTIEE production stack for the first run, and to
$0.000 on every recurring run. The 98.7% reduction headline holds
because the dominant savings come from replay, not from prompt size
shrinkage.

## Local mode

Local development is free. All three router tiers run the same Qwen3.5
0.8B GGUF with three different prompt envelopes. The first run takes
roughly 30 seconds on a CPU laptop; the replay path completes in under
two seconds because no model fires.

## Quality

Replay introduces no quality regression while the underlying interface
remains stable. When the interface mutates, the self-healing path runs a
re-grounding inference at the failed step and patches the template. This
is the single source of long-term cost; if a particular site rewrites
its DOM monthly, replay still amortises across the days between
mutations.
