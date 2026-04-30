"""Production stub for the local Qwen helper.

The real `agent/memory/local_llm.py` imports torch, transformers, and
huggingface-hub. CUTIEE's Render deployment skips the optional `local_llm`
dependency group, so those packages are not installed. The Render build
step replaces the real module with this stub so `agent.memory.reflector`
and `agent.memory.decomposer` still resolve `local_llm.shouldUseLocalLlmForUrl`
and `local_llm.generateText` without pulling the heavy ML dep tree.

Every entry point returns a safe default. `shouldUseLocalLlmForUrl` returns
False so the Qwen branch in the reflector / decomposer fallback chain is
never taken; the chain falls through to Gemini (or HeuristicReflector /
empty graph when no API key is set).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MODEL_ID = "stub"


def cacheRoot() -> Path:
    return Path("/dev/null")


def cachePaths() -> tuple[Path, ...]:
    return ()


def shouldUseLocalLlmForUrl(url: str = "") -> bool:
    del url
    return False


def isAvailable() -> bool:
    return False


def ensureModelCached() -> Path:
    raise RuntimeError("local_llm stub: model caching disabled in production")


def generateText(*args: Any, **kwargs: Any) -> str | None:
    del args, kwargs
    return None
