"""browser-use-backed Computer Use client wired to Gemini 3 Flash.

Phase 1 adds this as a second CuClient implementation alongside
`GeminiComputerUseClient`. The wrapped LLM is fixed at
`gemini-3-flash-preview` so both CU paths share a single credential
(`GEMINI_API_KEY`) and the cost table stays at Gemini Flash pricing.

browser-use ships a DOM indexer that returns actions keyed on element
index (`click_element_by_index`, `input_text`, etc.) rather than raw
pixels. Every action is translated into a canonical CUTIEE
`ActionType` so the replay planner at `agent/memory/replay.py` can
round-trip the stored procedural bullets. Native metadata rides inside
`Action.reasoning` behind the `__adapter_meta__{...}__` marker so the
audit schema stays frozen.

Installation: install the optional extra with
`pip install "cutiee[browser_use]"` or `uv sync --group browser_use`.
Calling `BrowserUseClient()` without the package installed raises
`RuntimeError` with remediation.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any

from ...harness.state import Action, ActionType
from ..cu_client import ComputerUseStep

DEFAULT_BROWSER_USE_MODEL = "gemini-3-flash-preview"

# browser-use drives Gemini 3 Flash in this plan. Pricing is the same as
# Gemini Flash ($0.15 / $0.60 per million), matching CU_PRICING at
# agent/routing/models/gemini_cu.py:41. The DOM observer adds ~500 extra
# input tokens per step for element indexing.
BROWSER_USE_PRICING: dict[str, tuple[float, float]] = {
    DEFAULT_BROWSER_USE_MODEL: (0.15, 0.60),
}

logger = logging.getLogger("cutiee.browser_use_client")

_INSTALL_HINT = (
    "browser-use is not installed. Install with `pip install "
    '"cutiee[browser_use]"` or `uv sync --group browser_use`.'
)

# Canonical map from browser-use action names to CUTIEE ActionType. The
# replay planner regex-parses these enum values out of bullet content,
# so every emission must land on one of these canonical names.
_NAME_TO_TYPE: dict[str, ActionType] = {
    "click_element_by_index": ActionType.CLICK_AT,
    "click_element": ActionType.CLICK_AT,
    "input_text": ActionType.TYPE_AT,
    "type_text": ActionType.TYPE_AT,
    "scroll_down": ActionType.SCROLL_AT,
    "scroll_up": ActionType.SCROLL_AT,
    "scroll": ActionType.SCROLL_AT,
    "go_to_url": ActionType.NAVIGATE,
    "navigate": ActionType.NAVIGATE,
    "send_keys": ActionType.KEY_COMBO,
    "key_combination": ActionType.KEY_COMBO,
    "wait": ActionType.WAIT,
    "done": ActionType.FINISH,
    "finished": ActionType.FINISH,
}

ADAPTER_META_PREFIX = "__adapter_meta__"
ADAPTER_META_SUFFIX = "__"


def _encodeAdapterMeta(payload: dict[str, Any]) -> str:
    return f"{ADAPTER_META_PREFIX}{json.dumps(payload, sort_keys = True)}{ADAPTER_META_SUFFIX}"


@dataclass
class BrowserUseClient:
    """CU client backed by the open-source browser-use Agent.

    Construction validates `GEMINI_API_KEY` because browser-use here is
    wired to Gemini 3 Flash. The import of `browser_use` itself happens
    lazily in `__post_init__` so importing this module never requires
    the optional dependency to be installed; construction does.
    """

    modelId: str = DEFAULT_BROWSER_USE_MODEL
    apiKey: str | None = None
    cdpUrl: str | None = None
    maxSteps: int = 25
    _agent: Any = field(default=None, init=False, repr=False)
    _browser: Any = field(default=None, init=False, repr=False)
    _pendingTask: str = field(default="", init=False, repr=False)
    _pendingUrl: str = field(default="", init=False, repr=False)
    _stepCursor: int = field(default=0, init=False, repr=False)
    _history: list[Any] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        key = self.apiKey or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is required for BrowserUseClient because "
                "browser-use is wired to Gemini 3 Flash in this plan."
            )
        self.apiKey = key
        try:
            import browser_use  # noqa: F401 - presence check only
        except ImportError as exc:
            raise RuntimeError(_INSTALL_HINT) from exc

    @property
    def name(self) -> str:
        return f"browser_use:{self.modelId}"

    def primeTask(self, taskDescription: str, currentUrl: str) -> None:
        self._pendingTask = taskDescription
        self._pendingUrl = currentUrl
        self._stepCursor = 0
        self._history.clear()
        self._agent = None
        self._browser = None

    async def nextAction(
        self,
        screenshotBytes: bytes,
        currentUrl: str,
    ) -> ComputerUseStep:
        del screenshotBytes  # browser-use reads the page directly over CDP

        if self._agent is None:
            self._agent = await self._buildAgent()

        try:
            rawStep = await self._drainNextRawStep()
        except Exception as exc:
            logger.warning("browser-use step failed: %r", exc)
            action = Action(
                type=ActionType.FINISH,
                reasoning=f"browser-use error: {exc!r}",
                model_used=self.modelId,
                cost_usd=0.0,
            )
            return ComputerUseStep(
                action=action,
                rawFunctionName="error",
                rawArgs={"exc": repr(exc)},
                costUsd=0.0,
            )

        canonical, rawFunctionName, rawArgs, meta = _toCanonicalAction(rawStep, currentUrl)
        costUsd = _estimateStepCost(rawStep, self.modelId)
        canonical.model_used = self.modelId
        canonical.cost_usd = costUsd
        metaPayload = {
            "adapter": "browser_use",
            "raw_function": rawFunctionName,
            "raw_args": rawArgs,
            **meta,
        }
        reasoning = canonical.reasoning or ""
        canonical.reasoning = f"{reasoning} {_encodeAdapterMeta(metaPayload)}".strip()
        self._stepCursor += 1
        return ComputerUseStep(
            action=canonical,
            rawFunctionName=rawFunctionName,
            rawArgs=rawArgs,
            costUsd=costUsd,
        )

    async def _buildAgent(self) -> Any:
        """Instantiate the browser-use Agent on demand.

        Separate method so tests can patch it cleanly. The agent is
        constructed with Gemini 3 Flash and attached via CDP to the
        browser controlled by CUTIEE's BrowserController.
        """
        from browser_use import Agent, Browser
        from browser_use.llm import ChatGoogle

        llm = ChatGoogle(model=self.modelId, api_key=self.apiKey)
        self._browser = Browser(cdp_url=self.cdpUrl) if self.cdpUrl else Browser()
        agent = Agent(
            task=self._pendingTask,
            llm=llm,
            browser=self._browser,
        )
        return agent

    async def _drainNextRawStep(self) -> Any:
        """Pull one raw action out of the browser-use Agent.

        browser-use's Agent loop does not expose a public per-step
        generator across all versions, so we call the internal
        `run_step` when available and fall back to iterating a single
        step via `run(max_steps=1)`. Both paths return enough
        information to build a `ComputerUseStep`.
        """
        agent = self._agent
        runStep = getattr(agent, "run_step", None)
        if callable(runStep):
            result = runStep()
            return await _maybeAwait(result)

        runMethod = getattr(agent, "run", None)
        if callable(runMethod):
            result = runMethod(max_steps=1)
            return await _maybeAwait(result)

        raise RuntimeError(
            "browser-use Agent exposes neither `run_step` nor `run`; "
            "upgrade browser-use to a version that supports per-step control."
        )


async def _maybeAwait(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value  # type: ignore[misc]
    if isinstance(value, Awaitable):
        return await value
    return value


def _toCanonicalAction(
    rawStep: Any,
    currentUrl: str,
) -> tuple[Action, str, dict[str, Any], dict[str, Any]]:
    """Translate a browser-use step into a canonical CUTIEE Action.

    Extracts the action name, arguments, and bounding-box center so the
    resulting Action carries a pixel coordinate usable by the existing
    Playwright executor and by replay. Native metadata is returned as a
    dict to be serialized into `Action.reasoning` by the caller.
    """
    rawFunctionName = _extractRawName(rawStep)
    rawArgs = _extractRawArgs(rawStep)
    actionType = _NAME_TO_TYPE.get(rawFunctionName, ActionType.WAIT)

    coordinate: tuple[int, int] | None = None
    value: str | None = None
    target: str = ""
    scrollDx = 0
    scrollDy = 0
    keys: list[str] | None = None

    if actionType in (ActionType.CLICK_AT, ActionType.TYPE_AT):
        bbox = rawArgs.get("bbox") or rawArgs.get("bounding_box") or rawArgs.get("rect")
        if bbox:
            coordinate = _bboxCenter(bbox)
        elif "x" in rawArgs and "y" in rawArgs:
            coordinate = (int(rawArgs["x"]), int(rawArgs["y"]))
        if actionType == ActionType.TYPE_AT:
            value = rawArgs.get("text") or rawArgs.get("value") or ""
    elif actionType == ActionType.SCROLL_AT:
        amount = int(rawArgs.get("amount", 600))
        if rawFunctionName == "scroll_up":
            scrollDy = -amount
        else:
            scrollDy = amount
    elif actionType == ActionType.NAVIGATE:
        target = rawArgs.get("url") or rawArgs.get("href") or currentUrl
    elif actionType == ActionType.KEY_COMBO:
        raw_keys = rawArgs.get("keys")
        if isinstance(raw_keys, str):
            keys = [k.strip() for k in raw_keys.replace("+", ",").split(",") if k.strip()]
        elif isinstance(raw_keys, list):
            keys = [str(k) for k in raw_keys]

    reasoning = rawArgs.get("reasoning") or _extractThought(rawStep)
    canonical = Action(
        type=actionType,
        target=target,
        value=value,
        reasoning=reasoning or "",
        coordinate=coordinate,
        keys=keys,
        scrollDx=scrollDx,
        scrollDy=scrollDy,
    )
    meta: dict[str, Any] = {}
    if "index" in rawArgs:
        meta["element_index"] = rawArgs["index"]
    if "selector" in rawArgs:
        meta["selector"] = rawArgs["selector"]
    return canonical, rawFunctionName, rawArgs, meta


def _extractRawName(rawStep: Any) -> str:
    for attr in ("action_name", "action", "name", "function"):
        value = getattr(rawStep, attr, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(rawStep, dict):
        for attr in ("action_name", "action", "name", "function"):
            value = rawStep.get(attr)
            if isinstance(value, str) and value:
                return value
    return "done"


def _extractRawArgs(rawStep: Any) -> dict[str, Any]:
    for attr in ("args", "arguments", "params", "payload"):
        value = getattr(rawStep, attr, None)
        if isinstance(value, dict):
            return value
    if isinstance(rawStep, dict):
        value = rawStep.get("args") or rawStep.get("arguments") or rawStep.get("params")
        if isinstance(value, dict):
            return value
    return {}


def _extractThought(rawStep: Any) -> str:
    for attr in ("thought", "reasoning", "thinking"):
        value = getattr(rawStep, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(rawStep, dict):
        return str(rawStep.get("thought") or rawStep.get("reasoning") or "")
    return ""


def _bboxCenter(bbox: Any) -> tuple[int, int] | None:
    if isinstance(bbox, dict):
        x = bbox.get("x")
        y = bbox.get("y")
        width = bbox.get("width", 0)
        height = bbox.get("height", 0)
        if x is None or y is None:
            return None
        return (int(x + width / 2), int(y + height / 2))
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        x1, y1, x2, y2 = bbox
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    return None


def _estimateStepCost(rawStep: Any, modelId: str) -> float:
    """Compute per-step cost using the BROWSER_USE_PRICING table.

    Prefers any cost fields the raw step already carries (input and
    output token counts) and falls back to a conservative per-step
    estimate matching the plan's cost comparison (~0.0006 per step for
    a ten-step task).
    """
    prices = BROWSER_USE_PRICING.get(modelId, (0.15, 0.60))
    priceIn, priceOut = prices
    inputTokens = _extractTokens(rawStep, ("input_tokens", "prompt_tokens", "in_tokens"))
    outputTokens = _extractTokens(rawStep, ("output_tokens", "completion_tokens", "out_tokens"))
    if inputTokens or outputTokens:
        return (inputTokens / 1e6) * priceIn + (outputTokens / 1e6) * priceOut
    return 0.0006


def _extractTokens(rawStep: Any, keys: tuple[str, ...]) -> int:
    for key in keys:
        value = getattr(rawStep, key, None)
        if isinstance(value, int):
            return value
        if isinstance(rawStep, dict):
            value = rawStep.get(key)
            if isinstance(value, int):
                return value
    return 0
