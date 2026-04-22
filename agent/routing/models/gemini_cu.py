"""Gemini Computer Use client.

Sends screenshots to a Gemini variant that supports the
`ComputerUse(environment="ENVIRONMENT_BROWSER")` tool. The model returns
coordinate-based function calls (`click_at`, `type_text_at`, `key_combination`,
`scroll_at`, `wait`, `open_web_browser`, ...) and the runner below
translates each function call into a CUTIEE `Action`.

Supported models (verified against the live API on 2026-04-19):
- `gemini-flash-latest`                 → tracks Google's latest flash, default
- `gemini-3-flash-preview`              → pinned 3-flash variant, flash pricing
- `gemini-2.5-computer-use-preview-10-2025` → specialty CU preview, 8× more expensive

Models that do NOT support CU (will 400 with "Computer Use is not enabled"):
- `gemini-3.1-flash-lite-preview`
- `gemini-3.1-flash` (also: model id doesn't exist)

Override with `CUTIEE_CU_MODEL` if you need a specific variant; otherwise
the default tracks the latest Flash so you get auto-upgrade on Google's
roll-outs without a code change.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ...harness.state import Action, ActionType
from ..cu_client import ComputerUseStep

# Default tracks Google's "latest flash" alias so a Google-side promotion
# of a new flash variant flows through automatically. Pin to
# `gemini-3-flash-preview` via CUTIEE_CU_MODEL if you need deterministic
# replay across Google model swaps.
DEFAULT_MODEL = os.environ.get("CUTIEE_CU_MODEL") or "gemini-flash-latest"

# Per-million-token pricing for CU-capable models. Pro-grade pricing kept
# only for the specialty preview because Google bills it at pro rates.
CU_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3-flash-preview": (0.15, 0.60),
    "gemini-flash-latest": (0.15, 0.60),
    "gemini-2.5-computer-use-preview-10-2025": (1.25, 5.00),
}
SUPPORTED_CU_MODELS = frozenset(CU_PRICING.keys())
FALLBACK_PRICING: tuple[float, float] = (0.15, 0.60)

# Legacy module-level constants kept as aliases so external imports
# don't break. Prefer CU_PRICING[modelId] in new code.
PRICING_INPUT, PRICING_OUTPUT = CU_PRICING[DEFAULT_MODEL]

logger = logging.getLogger("cutiee.gemini_cu")


# Map Gemini's function names to our ActionType enum.
_NAME_TO_TYPE: dict[str, ActionType] = {
    "open_web_browser": ActionType.OPEN_BROWSER,
    "click_at": ActionType.CLICK_AT,
    "type_text_at": ActionType.TYPE_AT,
    "type_text": ActionType.TYPE_AT,
    "key_combination": ActionType.KEY_COMBO,
    "scroll_at": ActionType.SCROLL_AT,
    "scroll": ActionType.SCROLL_AT,
    "wait": ActionType.WAIT,
    "wait_5_seconds": ActionType.WAIT,
    "navigate": ActionType.NAVIGATE,
    "go_to_url": ActionType.NAVIGATE,
    "finished": ActionType.FINISH,
    "task_complete": ActionType.FINISH,
}


@dataclass
class GeminiComputerUseClient:
    """Stateful client for Gemini's browser-environment Computer Use.

    The conversation must be maintained across turns: each step sends the
    new screenshot (as a function response) and waits for the next function
    call. We stash the running history on the instance so the orchestrator
    only has to call `nextAction(screenshotBytes, currentUrl)`.

    `historyKeepTurns` bounds the conversation: once the trailing history
    exceeds this many turn pairs, we drop the oldest screenshots so input
    tokens don't grow unbounded with run length. Each Gemini CU image is
    ~250 tokens; with the default 8 turns we cap input growth around 2 MB
    of base64 imagery per request.
    """
    modelId: str = DEFAULT_MODEL
    apiKey: str | None = None
    temperature: float = 0.1
    historyKeepTurns: int = 8
    history: list[Any] = field(default_factory = list)
    pendingCallId: str | None = None
    pendingCallName: str | None = None
    _client: Any = field(default = None, init = False, repr = False)
    _toolConfig: Any = field(default = None, init = False, repr = False)

    def __post_init__(self) -> None:
        key = self.apiKey or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is required for GeminiComputerUseClient.")
        if self.modelId not in SUPPORTED_CU_MODELS:
            logger.warning(
                "Gemini CU model %r is not in the verified-supported set %s. "
                "Live API may reject it with 400 'Computer Use is not enabled'. "
                "Set CUTIEE_CU_MODEL to one of the supported ids to silence this.",
                self.modelId, sorted(SUPPORTED_CU_MODELS),
            )
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key = key)
        self._toolConfig = types.Tool(computer_use = types.ComputerUse(environment = "ENVIRONMENT_BROWSER"))
        self.apiKey = key

    @property
    def name(self) -> str:
        return self.modelId

    def primeTask(self, taskDescription: str, currentUrl: str) -> None:
        """Reset the conversation and seed the first turn with the goal."""
        from google.genai import types

        self.history.clear()
        self.pendingCallId = None
        self.pendingCallName = None
        seedText = (
            f"Goal: {taskDescription}\n"
            f"You are operating a Chromium browser via the computer_use tool.\n"
            f"Current URL: {currentUrl or 'about:blank'}.\n"
            "Always issue exactly one tool call per turn. When the goal is met, "
            'call `finished` with `reason: "done"` to end the run.'
        )
        self.history.append(
            types.Content(role = "user", parts = [types.Part.from_text(text = seedText)])
        )

    async def nextAction(self, screenshotBytes: bytes, currentUrl: str) -> ComputerUseStep:
        """Send the latest screenshot and return the model's next action."""
        from google.genai import types

        # Wrap the screenshot as a function response if the model issued a
        # function call last turn; otherwise treat it as the initial user image.
        screenshotPart = types.Part.from_bytes(data = screenshotBytes, mime_type = "image/png")
        if self.pendingCallId is not None and self.pendingCallName is not None:
            funcResponse = types.Part.from_function_response(
                name = self.pendingCallName,
                response = {
                    "url": currentUrl,
                    "screenshot": "see attached image",
                },
            )
            # Some SDK versions accept inline parts on the function response;
            # fall back to a plain user message with the screenshot if needed.
            self.history.append(types.Content(role = "user", parts = [funcResponse, screenshotPart]))
        else:
            self.history.append(types.Content(role = "user", parts = [screenshotPart]))

        self._trimHistory()

        response = await self._client.aio.models.generate_content(
            model = self.modelId,
            contents = self.history,
            config = types.GenerateContentConfig(
                tools = [self._toolConfig],
                temperature = self.temperature,
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        inputTokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        outputTokens = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        # Per-model pricing so users who opt into the specialty preview
        # see accurate per-step costs without code changes.
        priceIn, priceOut = CU_PRICING.get(self.modelId, FALLBACK_PRICING)
        cost = inputTokens / 1_000_000 * priceIn + outputTokens / 1_000_000 * priceOut

        candidate = response.candidates[0]
        self.history.append(candidate.content)

        # Pick the first function_call part (the API may emit only one per turn).
        functionCall = None
        rawText = ""
        for part in candidate.content.parts or []:
            if getattr(part, "function_call", None):
                functionCall = part.function_call
                break
            if getattr(part, "text", None):
                rawText += part.text

        if functionCall is None:
            logger.warning("Gemini CU returned no function_call; raw text: %s", rawText[:200])
            self.pendingCallId = None
            self.pendingCallName = None
            return ComputerUseStep(
                action = Action(
                    type = ActionType.FINISH,
                    reasoning = rawText[:200] or "no_function_call",
                    model_used = self.modelId,
                    cost_usd = cost,
                    confidence = 0.4,
                ),
                rawFunctionName = "",
                rawArgs = {},
                costUsd = cost,
            )

        self.pendingCallId = getattr(functionCall, "id", None)
        self.pendingCallName = functionCall.name

        action = self._actionFromFunctionCall(functionCall.name, dict(functionCall.args or {}))
        action.cost_usd = cost
        action.model_used = self.modelId
        action.confidence = 0.85
        return ComputerUseStep(
            action = action,
            rawFunctionName = functionCall.name,
            rawArgs = dict(functionCall.args or {}),
            costUsd = cost,
        )

    def _actionFromFunctionCall(self, name: str, args: dict[str, Any]) -> Action:
        actionType = _NAME_TO_TYPE.get(name, ActionType.FINISH)
        coord = _extractCoordinate(args)
        text = args.get("text") or args.get("value") or args.get("query")
        keys = args.get("keys")
        if isinstance(keys, str):
            keys = [keys]

        if actionType == ActionType.CLICK_AT and coord is None:
            actionType = ActionType.FINISH
        if actionType == ActionType.NAVIGATE:
            target = str(args.get("url") or args.get("href") or "")
        else:
            target = ""

        scrollDx, scrollDy = 0, 0
        if actionType == ActionType.SCROLL_AT:
            scrollDx = int(args.get("dx") or args.get("delta_x") or 0)
            scrollDy = int(args.get("dy") or args.get("delta_y") or args.get("amount") or 500)

        return Action(
            type = actionType,
            target = target,
            value = str(text) if text is not None else None,
            coordinate = coord,
            keys = list(keys) if keys else None,
            scrollDx = scrollDx,
            scrollDy = scrollDy,
            reasoning = f"gemini_cu:{name}",
        )


    def _trimHistory(self) -> None:
        """Bound the trailing conversation to `historyKeepTurns` pairs.

        Always keeps the very first user message (the goal seed) so the
        model doesn't lose its task description. Each "turn" is a
        (user_msg, model_msg) pair, so we keep `2 * historyKeepTurns`
        trailing entries plus the seed.
        """
        if len(self.history) <= 2 * self.historyKeepTurns + 1:
            return
        seed = self.history[0]
        tail = self.history[-(2 * self.historyKeepTurns):]
        self.history = [seed, *tail]


def _extractCoordinate(args: dict[str, Any]) -> tuple[int, int] | None:
    if "coordinate" in args and isinstance(args["coordinate"], (list, tuple)) and len(args["coordinate"]) == 2:
        x, y = args["coordinate"]
        return (int(x), int(y))
    if "x" in args and "y" in args:
        return (int(args["x"]), int(args["y"]))
    if "position" in args and isinstance(args["position"], dict) and "x" in args["position"]:
        return (int(args["position"]["x"]), int(args["position"]["y"]))
    return None


ProgressCb = Callable[[int, ComputerUseStep], Awaitable[None] | None]


@dataclass
class MockComputerUseClient:
    """Deterministic CU client for tests + demo mode (CUTIEE_ENV unset).

    Returns a scripted sequence of actions, one per `nextAction` call.
    Mirrors the duck-typed interface ComputerUseRunner expects:
    `primeTask(taskDescription, currentUrl)` and async `nextAction(screenshot, url)`.
    When the script is exhausted it returns FINISH.
    """
    label: str = "mock-cu"
    actionsToReturn: list[Action] = field(default_factory = list)
    fixedCostUsd: float = 0.0
    cursor: int = 0
    callCount: int = 0
    primed: bool = False

    @property
    def name(self) -> str:
        return self.label

    @property
    def modelId(self) -> str:
        return self.label

    def primeTask(self, taskDescription: str, currentUrl: str) -> None:
        del taskDescription, currentUrl
        self.primed = True

    async def nextAction(self, screenshotBytes: bytes, currentUrl: str) -> ComputerUseStep:
        del screenshotBytes, currentUrl
        self.callCount += 1
        if self.cursor < len(self.actionsToReturn):
            action = self.actionsToReturn[self.cursor]
            self.cursor += 1
        else:
            action = Action(type = ActionType.FINISH, reasoning = "mock script exhausted")
        action.model_used = self.label
        action.cost_usd = self.fixedCostUsd
        return ComputerUseStep(
            action = action,
            rawFunctionName = action.type.value,
            rawArgs = {},
            costUsd = self.fixedCostUsd,
        )
