"""Confidence probe — derive a single scalar from token-level logprobs.

Two strategies:

* `confidenceFromLogprobs`: average the top-token logprob over the response
  and exponentiate. Used for Qwen via llama-server which exposes
  `--logprobs 10`.
* `confidenceFromHeuristic`: derived from the JSON parse success and
  presence/absence of required fields, used as a fallback when the model
  doesn't return logprobs.
"""
from __future__ import annotations

import math
from typing import Iterable


def confidenceFromLogprobs(logprobs: Iterable[float]) -> float:
    values = [lp for lp in logprobs if lp is not None]
    if not values:
        return 0.5
    mean = sum(values) / len(values)
    return float(min(1.0, max(0.0, math.exp(mean))))


def confidenceFromHeuristic(*, parsed: bool, hasTarget: bool, hasReasoning: bool) -> float:
    score = 0.5
    if parsed:
        score += 0.2
    if hasTarget:
        score += 0.2
    if hasReasoning:
        score += 0.1
    return min(1.0, score)
