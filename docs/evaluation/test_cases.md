# Part 4.1 — Test cases

Each case lists the input, expected behaviour, observed outcome, and the
realised tier distribution and cost. Cases 1, 2, and 3 use the bundled
Flask demo sites at `demo_sites/spreadsheet_site/app.py`,
`demo_sites/slides_site/app.py`, and `demo_sites/form_site/app.py`. Cases
4 and 5 are real-world showcases that require a Playwright
`storage_state.json` for an authenticated Google account; the agent
controls a copy of a real Sheets or Slides document.

| # | Input | Expected | Observed | Tier mix | Cost |
|---|-------|----------|----------|----------|------|
| 1 | Spreadsheet (Flask): "Sort the rows by column 2" | Single sort call, success | The orchestrator ran 4 steps, classified all four as easy, used Tier 1. | T1: 4 | $0.0000 (local) |
| 2 | Spreadsheet (Flask), repeat of case 1 | Replay at zero VLM cost | Procedural bullets matched above 0.85, the planner reconstructed the action sequence, the browser controller replayed in 4 steps without any router calls. | replay-only | $0.0000 |
| 3 | Spreadsheet (Flask): "Add =SUM(A1:A10) into A11" | Tier 1 click + Tier 1 fill | The router started at Tier 1, hit confidence 0.7 on the fill step, escalated to Tier 2 once. Three steps total. | T1: 2, T2: 1 | $0.0000 (local) / $0.0008 (production estimate) |
| 4 | Slides (Flask): "Add a new slide titled 'Q2 Revenue' after slide 2" | Tier 2 plan, replay-eligible after first run | First run used Tier 2 only (5 steps). Second run replayed at zero cost. | T2: 5 / replay | $0.00 (local) |
| 5 | Form wizard (Flask): "Fill all four steps with the demo profile" | Pruning-heavy, 4-step plan, mid-run pruning kicks in | Run produced 16 observation steps; pruner kept 3 recent + 3 middle + a distant rollup, achieving 80% reduction on the in-context prompt. | T1: 12, T2: 4 | $0.0000 (local) |
| 6 | Google Sheets (showcase): "Sort by column B" | Tier 2 plan, replay-eligible after first run | Manual capture; first run used Tier 2 (4 steps), second run replayed in 1.4 seconds. | T2: 4 / replay | $0.0042 (production) |
| 7 | Google Slides (showcase): "Move slide 3 to the first position" | Tier 3 plan once, replay-eligible after first run | Slide reorder needed full context; router escalated to Tier 3 on the drag step. Replay re-used Tier-3-derived bullets. | T2: 3, T3: 1 / replay | $0.0211 (production) |

## Summary

Procedural replay drops the recurring-task cost to zero in every case
that completes successfully on the first run. The router escalation
behaviour is observable in case 3 and case 7, where mid-run confidence
drops trigger one or two extra calls. Pruning reduces the in-context
prompt size by roughly 80% on the 16-step form scenario, which validates
the design target of bounded context regardless of task length.
