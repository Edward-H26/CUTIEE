"""Pre-download the local Qwen weights into CUTIEE's repo cache."""

from __future__ import annotations

from agent.memory.local_llm import MODEL_ID, ensureModelCached


def main() -> None:
    root = ensureModelCached()
    print(f"Cached {MODEL_ID} at {root}")


if __name__ == "__main__":
    main()
