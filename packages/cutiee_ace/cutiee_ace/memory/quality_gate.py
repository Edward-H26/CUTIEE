"""Quality gate that decides which `LessonCandidate`s reach the curator.

The gate combines three signals into a single score:

```
gate_score = 0.35 * output_valid + 0.35 * avg_lesson_quality + 0.30 * avg_confidence
```

A run is accepted iff:
* `gate_score >= 0.60`
* at least one lesson has `confidence >= 0.70`
* lessons aren't all identical (overlap below 0.95).

Rejection emits `QualityGateDiagnostics` so the UI can show the user why no
new bullets were stored.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..state import AgentState
from .reflector import LessonCandidate

ACCEPT_THRESHOLD = 0.60
MIN_TOP_CONFIDENCE = 0.70
MAX_OVERLAP = 0.95


@dataclass
class QualityGateDiagnostics:
    score: float = 0.0
    accepted: bool = False
    reasons: list[str] = field(default_factory = list)


@dataclass
class QualityGate:
    acceptThreshold: float = ACCEPT_THRESHOLD

    def apply(
        self,
        candidates: list[LessonCandidate],
        state: AgentState,
    ) -> tuple[list[LessonCandidate], QualityGateDiagnostics]:
        diagnostics = QualityGateDiagnostics()

        if not candidates:
            diagnostics.reasons.append("no_candidates")
            return [], diagnostics

        outputValid = 1.0 if state.isComplete else 0.0
        avgConfidence = sum(c.confidence for c in candidates) / len(candidates)
        avgQuality = sum(self._lessonQuality(c) for c in candidates) / len(candidates)
        score = 0.35 * outputValid + 0.35 * avgQuality + 0.30 * avgConfidence
        diagnostics.score = round(score, 4)

        topConfidence = max(c.confidence for c in candidates)
        if topConfidence < MIN_TOP_CONFIDENCE:
            diagnostics.reasons.append("top_confidence_low")

        overlap = self._overlap(candidates)
        if overlap >= MAX_OVERLAP:
            diagnostics.reasons.append("lessons_too_similar")

        if score < self.acceptThreshold:
            diagnostics.reasons.append(f"score_below_{self.acceptThreshold:.2f}")

        diagnostics.accepted = (
            score >= self.acceptThreshold
            and topConfidence >= MIN_TOP_CONFIDENCE
            and overlap < MAX_OVERLAP
        )

        if diagnostics.accepted:
            return candidates, diagnostics
        return [], diagnostics

    def _lessonQuality(self, candidate: LessonCandidate) -> float:
        contentScore = min(1.0, len(candidate.content.split()) / 20)
        tagScore = min(0.4, 0.1 * len(candidate.tags))
        topicScore = 0.2 if candidate.topic else 0.0
        return min(1.0, contentScore + tagScore + topicScore)

    def _overlap(self, candidates: list[LessonCandidate]) -> float:
        if len(candidates) <= 1:
            return 0.0
        contents = [c.content.strip().lower() for c in candidates]
        identicalPairs = 0
        totalPairs = 0
        for i in range(len(contents)):
            for j in range(i + 1, len(contents)):
                totalPairs += 1
                if contents[i] == contents[j]:
                    identicalPairs += 1
        return identicalPairs / totalPairs if totalPairs else 0.0
