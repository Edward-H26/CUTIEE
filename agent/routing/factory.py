"""Build the env-aware AdaptiveRouter.

`buildRouter()` is the single switch the orchestrator + Django services use.
Local mode produces three QwenLocalClients (one per prompt mode). Production
mode produces three GeminiCloudClients with different model ids.

There is no cross-environment fallback. If `CUTIEE_ENV` is missing or
invalid, the function raises so callers can surface a clear error to the UI.
"""
from __future__ import annotations

import os

from agent.routing.models.gemini_cloud import GeminiCloudClient
from agent.routing.models.mock import MockVLMClient
from agent.routing.models.qwen_local import QwenLocalClient
from agent.routing.router import AdaptiveRouter


def buildRouter() -> AdaptiveRouter:
    env = os.environ.get("CUTIEE_ENV")
    if env == "local":
        serverUrl = os.environ.get("QWEN_SERVER_URL")
        if not serverUrl:
            raise RuntimeError(
                "QWEN_SERVER_URL is required when CUTIEE_ENV=local. "
                "Run ./scripts/start_llama_server.sh."
            )
        return AdaptiveRouter(
            tier1 = QwenLocalClient(serverUrl = serverUrl, mode = "simple"),
            tier2 = QwenLocalClient(serverUrl = serverUrl, mode = "general"),
            tier3 = QwenLocalClient(serverUrl = serverUrl, mode = "full_context"),
        )
    if env == "production":
        if not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY is required when CUTIEE_ENV=production.")
        return AdaptiveRouter(
            tier1 = GeminiCloudClient(
                modelId = os.environ.get("GEMINI_MODEL_TIER1", "gemini-3.1-flash-lite"),
            ),
            tier2 = GeminiCloudClient(
                modelId = os.environ.get("GEMINI_MODEL_TIER2", "gemini-3.1-flash"),
            ),
            tier3 = GeminiCloudClient(
                modelId = os.environ.get("GEMINI_MODEL_TIER3", "gemini-3.1-pro"),
            ),
        )
    raise RuntimeError(
        f"CUTIEE_ENV must be 'local' or 'production', got {env!r}. No fallback."
    )


def buildMockRouter(*, label: str = "mock") -> AdaptiveRouter:
    """Used by Phase-1 tests, the Django services unit tests, and the
    Render demo path when the live model stack isn't available."""
    return AdaptiveRouter(
        tier1 = MockVLMClient(label = f"{label}-t1"),
        tier2 = MockVLMClient(label = f"{label}-t2"),
        tier3 = MockVLMClient(label = f"{label}-t3"),
    )
