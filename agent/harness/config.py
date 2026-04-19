"""Runtime configuration for the CUTIEE harness.

`Config.fromEnv()` validates every required key for the active `CUTIEE_ENV` and
raises immediately if anything is missing. There is no silent fallback; the
operator must pick local or production explicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen = True)
class Config:
    cutieeEnv: str
    qwenServerUrl: str | None
    geminiApiKey: str | None
    geminiTier1Model: str | None
    geminiTier2Model: str | None
    geminiTier3Model: str | None
    recencyWindow: int
    templateMatchThreshold: float
    confidenceThresholds: dict[int, float]
    maxStepsPerTask: int
    approvalRequiredOnHighRisk: bool

    @classmethod
    def fromEnv(cls) -> "Config":
        env = os.environ.get("CUTIEE_ENV")
        if env not in {"local", "production"}:
            raise RuntimeError(
                "CUTIEE_ENV must be set to 'local' or 'production'. See .env.example."
            )

        qwenUrl = os.environ.get("QWEN_SERVER_URL")
        geminiKey = os.environ.get("GEMINI_API_KEY")

        if env == "local" and not qwenUrl:
            raise RuntimeError(
                "QWEN_SERVER_URL is required when CUTIEE_ENV=local. "
                "Start llama-server via ./scripts/start_llama_server.sh."
            )
        if env == "production" and not geminiKey:
            raise RuntimeError(
                "GEMINI_API_KEY is required when CUTIEE_ENV=production."
            )

        return cls(
            cutieeEnv = env,
            qwenServerUrl = qwenUrl,
            geminiApiKey = geminiKey,
            geminiTier1Model = os.environ.get("GEMINI_MODEL_TIER1", "gemini-3.1-flash-lite"),
            geminiTier2Model = os.environ.get("GEMINI_MODEL_TIER2", "gemini-3.1-flash"),
            geminiTier3Model = os.environ.get("GEMINI_MODEL_TIER3", "gemini-3.1-pro"),
            recencyWindow = _envInt("CUTIEE_RECENCY_WINDOW", 3),
            templateMatchThreshold = _envFloat("CUTIEE_TEMPLATE_MATCH_THRESHOLD", 0.85),
            confidenceThresholds = {
                1: _envFloat("CUTIEE_CONFIDENCE_THRESHOLD_TIER1", 0.75),
                2: _envFloat("CUTIEE_CONFIDENCE_THRESHOLD_TIER2", 0.65),
                3: _envFloat("CUTIEE_CONFIDENCE_THRESHOLD_TIER3", 0.50),
            },
            maxStepsPerTask = _envInt("CUTIEE_MAX_STEPS_PER_TASK", 30),
            approvalRequiredOnHighRisk = _envBool("CUTIEE_REQUIRE_APPROVAL_HIGH_RISK", True),
        )


def _envInt(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _envFloat(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _envBool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
