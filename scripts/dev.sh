#!/usr/bin/env bash
# One-shot local dev stack: Neo4j (container) + llama-server (background) + Django (foreground).
# Django starts immediately; Qwen warms up in parallel; Neo4j bootstrap runs once.

set -euo pipefail

if [ -z "${CUTIEE_ENV:-}" ]; then
  set -a
  source .env 2>/dev/null || true
  set +a
fi

if [ "${CUTIEE_ENV:-}" != "local" ]; then
  echo "ERROR: CUTIEE_ENV must be 'local' for dev.sh (got: ${CUTIEE_ENV:-unset})" >&2
  exit 1
fi

./scripts/neo4j_up.sh

MODEL_DIR="${CUTIEE_MODEL_DIR:-./data/models}"
FILENAME="${QWEN_GGUF_FILENAME:-qwen3.5-0.8b-instruct-q4_k_m.gguf}"
MODEL_PATH="$MODEL_DIR/qwen/$FILENAME"

if [ ! -f "$MODEL_PATH" ]; then
  echo "Qwen GGUF not cached, downloading (~500MB, one-time)..."
  uv run python scripts/download_qwen.py
fi

mkdir -p data/audit_logs

echo "Starting llama-server in background on :8001 (warm-up ~5-10s from cache)..."
./scripts/start_llama_server.sh > data/audit_logs/llama.log 2>&1 &
LLAMA_PID=$!

cleanup() {
  echo ""
  echo "Stopping llama-server (PID $LLAMA_PID)..."
  kill "$LLAMA_PID" 2>/dev/null || true
  wait "$LLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting Django on :8000..."
echo "  UI will show 'Warming up...' until Qwen responds at :8001/health"
uv run python manage.py runserver
