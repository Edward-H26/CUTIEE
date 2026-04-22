# CUTIEE Render Deployment (Live Framebuffer)

This guide gets CUTIEE live on Render with a visible noVNC panel inside the dashboard's main content area. It reflects your 2026-04-22 state: paid Render account upgraded to **Standard** (2 GB RAM), paid Neo4j AuraDB, and the public URL `https://cutiee-1kqk.onrender.com`.

The live framebuffer requires two Render services: the Django web dashboard and a Dockerized worker running Xvfb + Chromium + x11vnc + websockify + noVNC. The web service embeds the worker's noVNC URL as an iframe in the Tasks detail page whenever an execution is running.

## 1. Architecture

```
                              Browser
                                │
                                │ HTTPS
                                ▼
  ┌──────────────────────────────────────────────┐
  │ cutiee-web (Standard Python, cutiee-1kqk)    │
  │   Django + HTMX                              │
  │   ComputerUseRunner                          │
  │   Playwright in-process  (headless Chromium) │
  │   Renders <iframe src=$CUTIEE_NOVNC_URL>     │
  └───────┬──────────────────────────────────────┘
          │ Cypher over bolt+s://
          ▼
     Neo4j AuraDB  (shared state)
          ▲
          │ Cypher over bolt+s://
          │
  ┌───────┴──────────────────────────────────────┐
  │ cutiee-worker (Standard Docker)              │
  │   Xvfb :99                                   │
  │   Chromium inside Xvfb  (--remote-debugging) │
  │   x11vnc --rfbport 5901                      │
  │   websockify --web=/usr/share/novnc 6080     │
  │   Writes :ProgressEvent / screenshots        │
  └──────────────────────────────────────────────┘
```

The iframe in the main panel points at `https://<cutiee-worker>.onrender.com/vnc.html` (or similar). Classmates see the agent's actual Chrome inside the dashboard, and can click into the frame as a manual takeover if the agent stalls.

## 2. Your Current Web Service

| Field | Value |
|-------|-------|
| Name | `CUTIEE` |
| Service ID | `srv-d7im9sf7f7vs739af3j0` |
| URL | `https://cutiee-1kqk.onrender.com` |
| Region | Oregon |
| Instance | Starter (0.5 CPU, 512 MB) — sufficient because real Chromium runs on the worker, not here |
| Runtime | Python 3 |
| Branch | `main` |
| Auto-deploy | Off (manual via deploy hook) |

The build command should be:

```
pip install uv && uv sync && uv run playwright install chromium && uv run python manage.py migrate --no-input && uv run python manage.py collectstatic --no-input && uv run python -m agent.persistence.bootstrap
```

And the start command:

```
uv run gunicorn cutiee_site.wsgi --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

These are what your Render dashboard already shows.

## 3. Required Env Vars on `CUTIEE` (web service)

Paste these in Render dashboard > CUTIEE > Environment. Mark everything except `DJANGO_DEBUG` as a secret.

```
# Core
CUTIEE_ENV=production
PYTHON_VERSION=3.12.7
DJANGO_SECRET_KEY=<generate a long random string>
DJANGO_DEBUG=False

# Auth
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>

# AuraDB
NEO4J_BOLT_URL=neo4j+s://<auradb-id>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<aura-password>
NEO4J_DATABASE=neo4j

# Gemini (drives both CU backends)
GEMINI_API_KEY=<your key>
CUTIEE_CU_BACKEND=gemini
CUTIEE_CU_MODEL=gemini-flash-latest

# Browser posture: the web dyno drives a REMOTE Chromium that lives
# on the cutiee-worker service. Playwright connects over CDP; the web
# dyno itself never launches Chromium, which is why Starter RAM is enough.
CUTIEE_USE_STUB_BROWSER=false
CUTIEE_BROWSER_HEADLESS=true
CUTIEE_BROWSER_CDP_URL=http://cutiee-worker:9222

# Runtime guardrails
CUTIEE_MAX_COST_USD_PER_TASK=0.50
CUTIEE_MAX_COST_USD_PER_HOUR=5.00
CUTIEE_MAX_COST_USD_PER_DAY=1.00
CUTIEE_HEARTBEAT_MINUTES=20
CUTIEE_HISTORY_KEEP_TURNS=8
CUTIEE_REPLAY_FRAGMENT_CONFIDENCE=0.80
CUTIEE_ALLOW_URL_FRAGMENTS=0

# Progress cache lives in AuraDB; no Redis needed
CUTIEE_PROGRESS_BACKEND=neo4j

# Live framebuffer target (set AFTER the worker deploys, see section 5)
# CUTIEE_NOVNC_URL=https://<cutiee-worker>.onrender.com/vnc.html
```

`DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` auto-include the Render hostname via `RENDER_EXTERNAL_HOSTNAME` detection in `cutiee_site/settings.py`, so you do not need to set them manually. The settings module also sets `SECURE_PROXY_SSL_HEADER` and `SESSION_COOKIE_SECURE` whenever `RENDER_EXTERNAL_HOSTNAME` is present, which is required for OAuth callbacks to succeed behind Render's TLS terminator.

## 4. Create the Worker Service (`cutiee-worker`)

This is the service that hosts the live framebuffer. Without it, the iframe has nothing to show.

1. In Render: **New +** > **Web Service**.
2. Connect the same GitHub repo (`github.com/Edward-H26/CUTIEE`, branch `main`).
3. **Name**: `cutiee-worker`.
4. **Region**: Oregon (match the web service and AuraDB).
5. **Runtime**: `Docker`.
6. **Dockerfile Path**: `Dockerfile.worker` (already in the repo).
7. **Docker Context**: leave blank (repo root).
8. **Instance Type**: Standard. Starter's 512 MB will OOM because the worker runs both Chromium and Xvfb plus websockify.

Save and let Render build. First build takes ~6-8 minutes (it downloads Playwright Chromium and the noVNC + websockify apt packages).

## 5. Worker Environment Variables

Paste these into the worker's Environment tab. Most duplicate the web service because the worker also writes to Neo4j.

```
CUTIEE_ENV=production
CUTIEE_USE_STUB_BROWSER=false
CUTIEE_BROWSER_HEADLESS=false

# Chromium runs inside Xvfb; expose it over CDP so the runner can
# attach or inspect. The Dockerfile already starts Chromium on port 9222.
CUTIEE_BROWSER_CDP_URL=http://localhost:9222

# Same creds as the web service
DJANGO_SECRET_KEY=<same value as cutiee-web>
NEO4J_BOLT_URL=neo4j+s://<auradb-id>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<aura-password>
NEO4J_DATABASE=neo4j
GEMINI_API_KEY=<your key>
CUTIEE_CU_BACKEND=gemini
CUTIEE_CU_MODEL=gemini-flash-latest

# Runtime guardrails (same as web)
CUTIEE_MAX_COST_USD_PER_TASK=0.50
CUTIEE_MAX_COST_USD_PER_HOUR=5.00
CUTIEE_MAX_COST_USD_PER_DAY=1.00
CUTIEE_HEARTBEAT_MINUTES=20
```

Do NOT set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` on the worker; it never serves the login page.

## 6. Expose Port 6080 and Copy the Worker URL

1. Worker > Settings > scroll to **Networking** or **Ports**.
2. Add port `6080` mapped to HTTP.
3. Render issues a public URL like `https://cutiee-worker-xyz.onrender.com`.
4. Open `https://cutiee-worker-xyz.onrender.com/vnc.html` in a browser tab directly. You should land on the noVNC viewer with a Connect button. Click it. You should see a dark Xvfb desktop with a fluxbox taskbar. No tasks are running yet so Chromium may or may not be visible. This confirms the worker is healthy.

## 7. Wire the iframe

Go back to the main `CUTIEE` web service > Environment. Add:

```
CUTIEE_NOVNC_URL=https://cutiee-worker-xyz.onrender.com/vnc.html
```

Trigger a manual deploy. After ~3 minutes the web service redeploys with the new env var. Visit `https://cutiee-1kqk.onrender.com`, sign in with Google, submit a task, and watch the Tasks detail page. The main panel now renders a card titled "Live browser" containing the noVNC iframe with autoconnect. You see the agent's Chrome in real time.

The iframe only appears when both conditions are met: `CUTIEE_NOVNC_URL` is set AND the active execution's status is `running`. Before a run starts or after it finishes, the panel shows other cards (preview approval, step log, cost summary).

## 8. Verification Checklist

```
[ ] Web service deploy succeeded: Render shows status "Live".
[ ] Worker service deploy succeeded: same.
[ ] https://cutiee-1kqk.onrender.com loads the landing page.
[ ] Google OAuth sign-in returns successfully.
[ ] https://<cutiee-worker>.onrender.com/vnc.html shows noVNC directly.
[ ] Submit a task with a simple URL such as https://example.com.
[ ] The Tasks detail page shows the preview approval card.
[ ] After you approve, the "Live browser" iframe appears.
[ ] You can see Chromium load the page in the framebuffer.
[ ] Step rows populate in the table below the iframe every 2 seconds.
[ ] At completion, cost appears in the Cost dashboard.
[ ] Neo4j contains a new :Execution and chained :Step nodes.
```

If the iframe stays empty even though the worker URL works in isolation, the browser is probably blocking the embed for mixed-content reasons. Confirm both services are on HTTPS (both Render URLs are by default).

## 9. Rollback

Render keeps recent deploys. On a bad push to either service:

1. Service > Deploys tab.
2. Click a prior green deploy > Rollback.

Rollback takes 2-3 minutes. Neo4j migrations are additive so no database rollback is needed.

## 10. Cost

| Item | Monthly |
|------|---------|
| `CUTIEE` web on Standard | $25 |
| `cutiee-worker` on Standard | $25 |
| AuraDB Free | $0 |
| Gemini Flash at ~$0.004 per 10-step task | ~$10-30 depending on cohort activity |
| **Total** | ~$60-80 |

The per-user daily cap of $1.00 bounds the model spend deterministically even if a classmate loops tasks.

## 11. What The Cohort Sees

1. Visit `https://cutiee-1kqk.onrender.com`.
2. Sign in with their Google account.
3. Land on the Tasks page. Click "New task", enter a description and a URL.
4. Approve the Phase 16 preview card.
5. Watch the live Chromium run inside the embedded noVNC iframe.
6. See step rows populate below the iframe and the cost tick up in real time.
7. At task completion, Audit and Memory tabs show the new records.

Taking over manually: if the agent stalls or routes to an unexpected page, click inside the iframe. Chromium receives the click through the VNC path and classmates can nudge the run back on track. SPEC.md section 8 treats disconnecting from the iframe as loss of consent, so closing the tab mid-run aborts the task with `completionReason="live_view_lost"`.
