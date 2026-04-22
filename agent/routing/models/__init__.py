"""Computer Use model clients.

Two implementations live here:

  * `GeminiComputerUseClient` — wraps `google.genai` with the
    `ComputerUse(environment="ENVIRONMENT_BROWSER")` tool. Talks to
    `gemini-flash-latest` by default; override via `CUTIEE_CU_MODEL`.
  * `MockComputerUseClient` — returns scripted actions from a list,
    no API call. Used by tests and demo mode.

Both expose the same duck-typed surface that `ComputerUseRunner`
consumes: `primeTask(taskDescription, currentUrl)` and async
`nextAction(screenshot, currentUrl) -> ComputerUseStep`.
"""
from ..cu_client import ComputerUseStep, CuClient
from .browser_use_client import BrowserUseClient
from .gemini_cu import (
    GeminiComputerUseClient,
    MockComputerUseClient,
)

__all__ = [
    "BrowserUseClient",
    "ComputerUseStep",
    "CuClient",
    "GeminiComputerUseClient",
    "MockComputerUseClient",
]
