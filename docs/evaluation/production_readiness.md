# Part 4.5 — Production readiness

## Deployment

CUTIEE deploys to Render via `render.yaml`. The build step runs
`uv sync`, collects static files, and applies the Neo4j constraints and
indexes via `agent.persistence.bootstrap`. The runtime command is
Gunicorn against `cutiee_site.wsgi`. Whitenoise serves static assets
inline. Django framework tables live in the SQLite file at
`data/django_internals.sqlite3`; the Site object is upserted on the
first request.

`SECURITY_HARDENING.md` would be a follow-on document for a real
launch; the INFO490 deployment ships with the standard Django defaults
plus Whitenoise's compressed manifest storage.

## Secrets

Every secret loads from environment variables. The required keys are
`CUTIEE_ENV`, `DJANGO_SECRET_KEY`, `GEMINI_API_KEY`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `NEO4J_BOLT_URL`,
`NEO4J_USERNAME`, and `NEO4J_PASSWORD`. The Render dashboard sets each
one explicitly with `sync: false`. There is no fallback to file-based
secrets.

## Monitoring

The cost dashboard, the audit log, and the memory dashboard expose the
operational signals that matter day-to-day: total spend, task throughput,
tier distribution, and replay efficiency. The VLM health endpoint
(`/api/vlm-health/`) is wired to an HTMX banner so users see model
state in real time.

The recommended addition for production is structured JSON logging via
`structlog` plus an external alerting layer; both are scoped out of the
INFO490 deliverable.

## Rate limits

Gemini Flash has free-tier and paid-tier rate caps. The CU client does
not implement client-side rate limiting; in production the recommended
pattern is to wrap the Gemini client in `tenacity` retries with
exponential backoff.

> **Note — pre-pivot:** The original design also discussed scaling a
> local llama-server (Qwen 0.8B) per CPU core for offline inference.
> That path was removed in 2026-04 when the agent collapsed to
> screenshot-based Computer Use (no Qwen-scale model supports the
> ComputerUse tool). Local mode now runs `MockComputerUseClient`.

## Failure modes and handling

- Neo4j unavailable: every Cypher call wraps `ServiceUnavailable` and
  raises a `RuntimeError` with a remediation hint. The web tier returns
  500 with the message instead of silently degrading.
- VLM unavailable: `vlm_health` returns `loading` or `unavailable`, the
  task submit form disables, and the user sees a banner.
- Browser automation unavailable: the services layer falls back to
  `StubBrowserController`. The agent still completes, the task records
  zero real browser actions, and the audit log marks every step as a
  stub run. Production with real Playwright requires a worker dyno with
  the browser binary installed.
- Approval gate timeout: the gate waits indefinitely by default; a
  `requireApproval=False` orchestrator config bypass exists for tests.
  Production should add a wall-clock timeout in the gate decider.

## Privacy

User data is scoped per user via the `OWNS` relationship pattern in
every Cypher query. The repository functions take `userId` as the first
argument so cross-tenant reads are impossible at the query level.
Credentials persist as `:MemoryBullet` nodes with `is_credential=True`
and content encrypted at rest with `cryptography.fernet`; the retrieval
path filters credential bullets out of every prompt block, so a model
never sees a decrypted secret.

## Known follow-ups

- Move the progress cache from process memory to Redis so the web tier
  can scale horizontally.
- Add a Playwright worker dyno with `playwright install chromium` baked
  into the build.
- Surface a credential-rotation reminder when a stored OAuth/Google
  session begins to fail authentication checks.
- Replace the heuristic difficulty classifier with a small fine-tuned
  classifier once enough labeled data accumulates.
