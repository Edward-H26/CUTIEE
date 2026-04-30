"""Rule-based summarizer for distant trajectory steps.

We don't burn VLM cycles on the summary; a deterministic rollup of action
counts per type is enough for the model to reconstruct what happened far
enough back.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from ..harness.state import ObservationStep


def ruleBasedSummary(distantSteps: Iterable[ObservationStep]) -> str:
    counter: Counter[str] = Counter()
    domains: set[str] = set()
    failures = 0
    for step in distantSteps:
        if step.action is None:
            continue
        counter[step.action.type.value] += 1
        if step.url and "://" in step.url:
            domains.add(step.url.split("://", 1)[1].split("/", 1)[0])
        if not step.verificationOk:
            failures += 1

    if not counter:
        return "(no distant history)"

    parts = [f"{count}x {kind}" for kind, count in counter.most_common()]
    summary = "earlier: " + ", ".join(parts)
    if domains:
        summary += f"; domains: {', '.join(sorted(domains))}"
    if failures:
        summary += f"; {failures} earlier step(s) failed verification"
    return summary
