#!/usr/bin/env bash
# One-shot local dev stack: Neo4j (container) + Django (foreground).
#
# CUTIEE_ENV=local runs the MockComputerUseClient (scripted demo actions)
# for the browser-control loop, plus a cached `Qwen/Qwen3.5-0.8B` (via HF
# transformers, see agent/memory/local_llm.py) for memory-side reflection
# and action decomposition when the task targets `localhost`. Pre-cache
# the Qwen weights once with `python scripts/cache_local_qwen.py`.
#
# To drive a real browser, set CUTIEE_ENV=production and supply
# GEMINI_API_KEY. Production never runs Qwen; the reflector falls back
# to Gemini Flash, then HeuristicReflector if the API key is absent.

set -euo pipefail

if [ -z "${CUTIEE_ENV:-}" ]; then
  set -a
  source .env 2>/dev/null || true
  set +a
fi

if [ "${CUTIEE_ENV:-}" != "local" ] && [ "${CUTIEE_ENV:-}" != "production" ]; then
  echo "ERROR: CUTIEE_ENV must be 'local' (mock CU) or 'production' (real Gemini CU); got: ${CUTIEE_ENV:-unset}" >&2
  exit 1
fi

./scripts/neo4j_up.sh

mkdir -p data/audit_logs

echo "Starting Django on :8000..."
echo "  Mode: ${CUTIEE_ENV} (${CUTIEE_ENV/local/MockComputerUseClient — scripted demo}${CUTIEE_ENV/production/Gemini Computer Use — real browser})"
uv run python manage.py runserver
