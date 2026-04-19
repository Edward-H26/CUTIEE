"""Download Qwen3.5 0.8B Q4_K_M GGUF into data/models/qwen/.

Raises if QWEN_MODEL_ID or QWEN_GGUF_FILENAME are unset. No fallback to any other
model size; CUTIEE explicitly chose this parameter count for local dev.
"""
import os
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

MODEL_DIR = Path(os.environ.get("CUTIEE_MODEL_DIR", "./data/models"))
REPO_ID = os.environ.get("QWEN_MODEL_ID")
FILENAME = os.environ.get("QWEN_GGUF_FILENAME")


def main() -> None:
    if not REPO_ID or not FILENAME:
        print(
            "ERROR: QWEN_MODEL_ID and QWEN_GGUF_FILENAME must be set. "
            "See .env.example.",
            file = sys.stderr,
        )
        sys.exit(1)
    target = MODEL_DIR / "qwen"
    target.mkdir(parents = True, exist_ok = True)
    path = hf_hub_download(repo_id = REPO_ID, filename = FILENAME, local_dir = str(target))
    print(f"Downloaded: {path}")


if __name__ == "__main__":
    main()
