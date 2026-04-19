"""Runtime configuration for the CUTIEE harness.

`Config.fromEnv()` validates every required key for the active `CUTIEE_ENV` and
raises immediately if anything is missing. There is no silent fallback; the
operator must pick local or production explicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .env_utils import envBool, envFloat, envInt


@dataclass(frozen = True)
class Config:
    cutieeEnv: str
    geminiApiKey: str | None
    cuModel: str
    templateMatchThreshold: float
    maxStepsPerTask: int
    approvalRequiredOnHighRisk: bool
    screenshotTtlDays: int

    @classmethod
    def fromEnv(cls) -> "Config":
        env = os.environ.get("CUTIEE_ENV")
        if env not in {"local", "production"}:
            raise RuntimeError(
                "CUTIEE_ENV must be set to 'local' or 'production'. See .env.example."
            )

        geminiKey = os.environ.get("GEMINI_API_KEY")
        if env == "production" and not geminiKey:
            raise RuntimeError(
                "GEMINI_API_KEY is required when CUTIEE_ENV=production. "
                "Computer Use needs a real Gemini key; there is no offline mode."
            )

        return cls(
            cutieeEnv = env,
            geminiApiKey = geminiKey,
            cuModel = os.environ.get("CUTIEE_CU_MODEL", "gemini-flash-latest"),
            templateMatchThreshold = envFloat("CUTIEE_TEMPLATE_MATCH_THRESHOLD", 0.85),
            maxStepsPerTask = envInt("CUTIEE_MAX_STEPS_PER_TASK", 30),
            approvalRequiredOnHighRisk = envBool("CUTIEE_REQUIRE_APPROVAL_HIGH_RISK", True),
            screenshotTtlDays = envInt("CUTIEE_SCREENSHOT_TTL_DAYS", 3),
        )
