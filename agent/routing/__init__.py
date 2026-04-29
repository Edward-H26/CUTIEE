"""Model clients used by the agent runner.

Pre-2026-04 this package hosted the multi-tier `AdaptiveRouter`,
difficulty classifier, confidence probes, and DOM-based clients
(GeminiCloudClient, QwenLocalClient, MockVLMClient). All of that was
removed once Gemini Flash gained the ComputerUse tool at flash pricing
and the agent collapsed to a single screenshot-based runner.

What's left: just `agent.routing.models.gemini_cu`, exposing the live
`GeminiComputerUseClient` and the deterministic `MockComputerUseClient`
used by tests + demo mode (CUTIEE_ENV unset / non-production).

The local Qwen 0.8B helper that drives memory-side reflection /
decomposition for localhost tasks lives at `agent/memory/local_llm.py`
(it is NOT a CU client; the screenshot loop stays Gemini-only).
"""
