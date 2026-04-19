#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${CUTIEE_MODEL_DIR:-./data/models}"
FILENAME="${QWEN_GGUF_FILENAME:-qwen3.5-0.8b-instruct-q4_k_m.gguf}"
MODEL_PATH="$MODEL_DIR/qwen/$FILENAME"

if [ ! -f "$MODEL_PATH" ]; then
  echo "ERROR: Model not found at $MODEL_PATH" >&2
  echo "Run: uv run python scripts/download_qwen.py" >&2
  exit 1
fi

if ! command -v llama-server &> /dev/null; then
  echo "ERROR: llama-server binary not on PATH" >&2
  echo "  macOS:  brew install llama.cpp" >&2
  echo "  Linux:  build from https://github.com/ggml-org/llama.cpp" >&2
  exit 1
fi

llama-server \
  -m "$MODEL_PATH" \
  --host 0.0.0.0 --port 8001 \
  --ctx-size 8192 \
  --threads 8 \
  --logprobs 10
