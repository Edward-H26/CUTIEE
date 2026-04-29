#!/usr/bin/env bash
# Local pre-push check: assert that torch / transformers do NOT leak into
# the base [project] dependencies that `uv sync` installs on Render. These
# are the libraries that actually load the Qwen 0.8B model; they must
# stay in the optional `local_llm` group only.
#
# huggingface-hub is intentionally NOT checked: fastembed (used for the
# BAAI/bge-small-en-v1.5 embedding model in agent/memory/embeddings.py)
# pulls it as a transitive dependency. On its own hf-hub cannot load a
# causal LM — it is only a thin client for the Hub API. The Qwen runtime
# still requires torch + transformers, both gated to the local_llm group.
#
# Usage: bash scripts/verify_render_isolation.sh
# Exit:  0 = clean; non-zero = torch or transformers leaked into base deps.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

REQ_FILE="$(mktemp)"
trap 'rm -f "$REQ_FILE"' EXIT

uv pip compile pyproject.toml -o "$REQ_FILE" >/dev/null 2>&1

LEAKS="$(grep -E "^(torch|transformers)(==|>=|<=|~=|!=|\b)" "$REQ_FILE" || true)"

if [ -n "$LEAKS" ]; then
    echo "ERROR: heavy ML dep leaked into base [project] dependencies:" >&2
    echo "$LEAKS" >&2
    echo "Move it back to the [dependency-groups].local_llm group in pyproject.toml." >&2
    exit 1
fi

if [ ! -f agent/memory/local_llm_stub.py ]; then
    echo "ERROR: agent/memory/local_llm_stub.py is missing." >&2
    echo "Render's buildCommand replaces the real local_llm with this stub." >&2
    exit 1
fi

echo "OK: torch / transformers are isolated to the optional local_llm group."
echo "OK: production stub at agent/memory/local_llm_stub.py is present."
echo "Note: huggingface-hub is allowed as a transitive dep of fastembed."
