"""Formal Protocol that every Computer Use client in CUTIEE must satisfy.

The runtime has one agent loop (`ComputerUseRunner`) and at least one CU
client driving it (currently `GeminiComputerUseClient`, plus the
deterministic `MockComputerUseClient` and the new `BrowserUseClient`).
Before this module existed the client contract was duck-typed with an
`Any` hint on `ComputerUseRunner.client`, which made it easy for a new
adapter to ship with a subtly different signature and break the loop at
runtime instead of at import.

Every CU client now satisfies the `CuClient` runtime-checkable Protocol:

  * `name: str`                     identifies the client in audit records
  * `primeTask(task, url) -> None`  sync seed call, runs once per task
  * async `nextAction(screenshotBytes, currentUrl) -> ComputerUseStep`

`ComputerUseStep` lives here as the canonical return type so new adapters
never have to import the Gemini module just to return a step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..harness.state import Action


@dataclass
class ComputerUseStep:
    action: Action
    rawFunctionName: str
    rawArgs: dict[str, Any]
    costUsd: float


@runtime_checkable
class CuClient(Protocol):
    """Contract every Computer Use client must honor.

    The runner calls `primeTask` once per task to seed any stateful
    conversation, then calls `nextAction` once per step. An adapter that
    violates the signature will fail `isinstance(client, CuClient)` at
    runner construction time instead of at the first screenshot.
    """

    @property
    def name(self) -> str: ...

    def primeTask(self, taskDescription: str, currentUrl: str) -> None: ...

    async def nextAction(
        self,
        screenshotBytes: bytes,
        currentUrl: str,
    ) -> ComputerUseStep: ...
