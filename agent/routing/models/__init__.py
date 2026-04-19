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
from .gemini_cu import (
    ComputerUseStep,
    GeminiComputerUseClient,
    MockComputerUseClient,
)

__all__ = [
    "ComputerUseStep",
    "GeminiComputerUseClient",
    "MockComputerUseClient",
]
