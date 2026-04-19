# Part 4.2 — Failure analysis

## Case A: spreadsheet toolbar moved between runs

The Sheets toolbar redesign in the showcase test rendered a previously
recorded selector unreachable. The replay attempt clicked a button that
no longer existed, the verification step returned `verificationOk=False`,
and the orchestrator handed control back to the router. The router
classified the step as medium difficulty, used Tier 2 to re-ground the
selector, and the curator emitted a `DeltaUpdate` that decreased the
failed bullet's `procedural_strength` by 1.0 and added a replacement
bullet pointing at the new selector. The third run replayed cleanly.

The cost delta was about one Tier-2 inference for the broken step,
roughly $0.0009 in production. The replay path remained cheaper than the
original full-pipeline run because only the failed step re-grounded.

## Case B: Qwen low confidence on slide reorder

In local mode, the slide reorder action requires a drag, which Qwen3.5
0.8B regularly returns at confidence below 0.5. The router's escalation
loop walked from Tier 1 to Tier 2 to Tier 3 (still Qwen, but with the
full-context prompt), where the model produced a coherent action plan.
The audit log captured all three calls; the per-step cost rolled up
across escalations.

In production this maps directly to escalating from `gemini-3.1-flash-lite`
to `gemini-3.1-flash` and finally to `gemini-3.1-pro`. The expected cost
delta on the production stack is around $0.02 for the single slide
reorder step.

## Case C: Google session expired mid-task

The Playwright `storage_state.json` aged out during a long showcase
session. Every navigation returned the Google login page, and the agent
correctly identified the page change because the DOM hash diverged from
the recorded baseline. The orchestrator finished the run with
`completionReason="action_failed:sign-in-required"` and surfaced the
state in the UI. The user re-captured the storage state and re-ran the
task. The replay cluster matched on the second attempt.

This case argues for a credential-rotation reminder in the UI; the
production-readiness doc captures it as a follow-up item.
