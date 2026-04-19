#!/usr/bin/env bash
# Start the local Neo4j 5 container and run the idempotent CUTIEE bootstrap.
# In production (CUTIEE_ENV=production), Neo4j is AuraDB and this script is a no-op.

set -euo pipefail

if [ -z "${CUTIEE_ENV:-}" ]; then
  set -a
  source .env 2>/dev/null || true
  set +a
fi

if [ "${CUTIEE_ENV:-}" != "local" ]; then
  echo "NEO4J_BOLT_URL points at AuraDB in production, no container to start." >&2
  exit 0
fi

if ! command -v docker &> /dev/null; then
  echo "ERROR: docker binary not on PATH." >&2
  echo "Install Docker Desktop (https://www.docker.com/products/docker-desktop/)" >&2
  echo "or Colima (https://github.com/abiosoft/colima) and retry." >&2
  exit 1
fi

mkdir -p data/neo4j/data data/neo4j/logs

echo "Starting cutiee-neo4j container..."
docker compose up -d neo4j

echo "Waiting for bolt port 7687..."
for _ in $(seq 1 30); do
  if nc -z localhost 7687 2>/dev/null; then
    echo "Bolt port open."
    break
  fi
  sleep 1
done

if ! nc -z localhost 7687 2>/dev/null; then
  echo "ERROR: Neo4j bolt port still closed after 30s. Check docker logs cutiee-neo4j." >&2
  exit 1
fi

echo "Running CUTIEE Cypher bootstrap..."
uv run python -m agent.persistence.bootstrap

echo ""
echo "Neo4j ready at bolt://localhost:7687"
echo "Browser UI     : http://localhost:7474"
echo "Username       : neo4j"
echo "Password       : value of NEO4J_PASSWORD in .env"
