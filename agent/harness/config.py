"""Runtime configuration for the CUTIEE harness.

`Config.fromEnv()` validates every required key for the active `CUTIEE_ENV` and
raises immediately if anything is missing. There is no silent fallback; the
operator must pick local or production explicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .env_utils import envBool, envFloat, envInt


ALLOWED_CU_BACKENDS: frozenset[str] = frozenset({"gemini", "browser_use"})


@dataclass(frozen = True)
class Config:
    cutieeEnv: str
    geminiApiKey: str | None
    cuModel: str
    cuBackend: str
    templateMatchThreshold: float
    maxStepsPerTask: int
    approvalRequiredOnHighRisk: bool
    screenshotTtlDays: int
    maxCostUsdPerTask: float
    maxCostUsdPerHour: float
    maxCostUsdPerDay: float
    historyKeepTurns: int
    replayFragmentConfidence: float
    allowUrlFragments: bool
    heartbeatMinutes: int

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

        cuBackend = os.environ.get("CUTIEE_CU_BACKEND", "gemini").strip().lower()
        if cuBackend not in ALLOWED_CU_BACKENDS:
            raise RuntimeError(
                f"CUTIEE_CU_BACKEND={cuBackend!r} is not recognized. "
                f"Valid values are {sorted(ALLOWED_CU_BACKENDS)}. "
                "Both backends require GEMINI_API_KEY because browser-use is "
                "backed by Gemini 3 Flash."
            )
        if cuBackend == "browser_use" and not geminiKey:
            raise RuntimeError(
                "GEMINI_API_KEY is required when CUTIEE_CU_BACKEND=browser_use "
                "because browser-use is wired to Gemini 3 Flash."
            )

        return cls(
            cutieeEnv = env,
            geminiApiKey = geminiKey,
            cuModel = os.environ.get("CUTIEE_CU_MODEL", "gemini-flash-latest"),
            cuBackend = cuBackend,
            templateMatchThreshold = envFloat("CUTIEE_TEMPLATE_MATCH_THRESHOLD", 0.85),
            maxStepsPerTask = envInt("CUTIEE_MAX_STEPS_PER_TASK", 30),
            approvalRequiredOnHighRisk = envBool("CUTIEE_REQUIRE_APPROVAL_HIGH_RISK", True),
            screenshotTtlDays = envInt("CUTIEE_SCREENSHOT_TTL_DAYS", 3),
            maxCostUsdPerTask = envFloat("CUTIEE_MAX_COST_USD_PER_TASK", 0.50),
            maxCostUsdPerHour = envFloat("CUTIEE_MAX_COST_USD_PER_HOUR", 5.00),
            maxCostUsdPerDay = envFloat("CUTIEE_MAX_COST_USD_PER_DAY", 1.00),
            historyKeepTurns = envInt("CUTIEE_HISTORY_KEEP_TURNS", 8),
            replayFragmentConfidence = envFloat("CUTIEE_REPLAY_FRAGMENT_CONFIDENCE", 0.80),
            allowUrlFragments = envBool("CUTIEE_ALLOW_URL_FRAGMENTS", False),
            heartbeatMinutes = envInt("CUTIEE_HEARTBEAT_MINUTES", 20),
        )
