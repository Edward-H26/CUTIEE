# CUTIEE Render Deployment (Live Framebuffer)

This guide gets CUTIEE live on Render with a visible noVNC panel inside the dashboard's main content area. It reflects your 2026-04-22 state: paid Render account upgraded to **Standard** (2 GB RAM), paid Neo4j AuraDB, and the public URL `https://cutiee-1kqk.onrender.com`.

The live framebuffer requires two Render services: the Django web dashboard and a Dockerized worker running Xvfb + Chromium + x11vnc + websockify + noVNC. The web service embeds the worker's noVNC URL as an iframe in the Tasks detail page whenever an execution is running.

Both services are declared in `render.yaml` as an IaC Blueprint, so you only touch the dashboard to paste secrets and to read the public URL once the worker deploys. Nothing in this guide requires clicking through a "Networking" or "Ports" UI; the blueprint sets `PORT=6080` on the worker and Render routes HTTPS to that port automatically.

## 1. Architecture

```
                              Browser
                             │         │
                     HTTPS   │         │  noVNC WebSocket
                     HTMX    │         │  (iframe embed)
                             ▼         ▼
  ┌──────────────────────────────────────┐   ┌────────────────────────────────┐
  │ cutiee-web (Standard Python,         │   │ cutiee-worker (Standard Docker)│
  │             cutiee-1kqk)             │   │                                │
  │   Django + HTMX                      │   │   Xvfb :99                     │
  │   allauth Google OAuth               │   │   fluxbox                      │
  │   ComputerUseRunner                  │──►│   Chromium (headed)            │
  │   BrowserController                  │CDP│     --remote-debugging-port    │
  │     (Playwright, connect_over_cdp)   │9222│        =9222  on 0.0.0.0      │
  │   CuClient (Gemini CU)               │   │   x11vnc --rfbport 5901        │
  │   Renders <iframe src=               │   │   websockify :6080             │
  │     $CUTIEE_NOVNC_URL>               │   │                                │
  │                                      │   │   (No Python at runtime;       │
  │                                      │   │    no Neo4j connection.)       │
  └───────┬──────────────────────────────┘   └────────────────────────────────┘
          │ Cypher over bolt+s://
          ▼
     Neo4j AuraDB  (shared state; only cutiee-web writes here)
```

`cutiee-web` is the only Python process in the deployment. It runs the CU loop, drives the worker's Chromium via Chrome DevTools Protocol (`connect_over_cdp("http://cutiee-worker:9222")`), and persists every `:Step`, `:Screenshot`, `:CostLedger`, and memory bullet to AuraDB. `cutiee-worker` is a headed-browser container whose only responsibility is to host Chromium inside Xvfb and stream the framebuffer through noVNC.

The iframe in the main panel points at `https://<cutiee-worker-hostname>.onrender.com/vnc.html`. Classmates see the agent's actual Chrome inside the dashboard, and can click into the frame as a manual takeover if the agent stalls. CDP traffic between the two services stays on Render's private network; only HTTPS and the noVNC WebSocket are publicly exposed.

## 2. Services Declared in `render.yaml`

Both services below are managed by the Blueprint at the repo root. Push the file, point Render at the repo once via **New +** > **Blueprint**, and Render provisions both services in lockstep. After the first apply you never touch the dashboard for configuration; only secrets and the post-deploy `CUTIEE_NOVNC_URL` are dashboard-entered.

| Service | Name | Runtime | Plan | Role |
|---------|------|---------|------|------|
| Web | `cutiee-web` | Python 3.12 | Standard | Django + HTMX dashboard. Drives the worker's Chromium over CDP. Public. |
| Worker | `cutiee-worker` | Docker (`Dockerfile.worker`) | Standard | Xvfb + fluxbox + x11vnc + websockify + Chromium. Serves noVNC publicly on `PORT=6080`; CDP on 9222 is private-network only. |

Existing dashboard-created services should be adopted into the blueprint instead of duplicated. In Render: **Blueprints** > your blueprint > **Sync**. If a service name in `render.yaml` matches an existing service, Render links them; otherwise it creates a new one. If your existing web service is literally named `CUTIEE` (from the pre-blueprint era), rename it to `cutiee-web` in the dashboard first or update `render.yaml` to use `CUTIEE`. The same applies to `cutiee-worker`.

The build and start commands for `cutiee-web` are pinned in `render.yaml`:

```
# buildCommand
uv sync && uv run playwright install chromium && uv run python manage.py migrate --no-input && uv run python manage.py collectstatic --no-input && uv run python -m agent.persistence.bootstrap

# startCommand
uv run gunicorn cutiee_site.wsgi --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

The `cutiee-worker` service has no custom build or start command because the Dockerfile's `ENTRYPOINT` + `CMD` already run `tini` + `start-worker.sh`, which launches the five long-lived processes.

## 3. Secrets to Paste After the First Blueprint Sync

Everything in `render.yaml` is either a literal value or marked `sync: false` (secret). Render prompts for the `sync: false` keys during the first sync. Paste them then, or any time afterwards in **Environment** > **Edit secrets**.

**`cutiee-web` secrets:**

```
DJANGO_SECRET_KEY                # auto-generated by Render if left blank
GOOGLE_CLIENT_ID                 # Google Cloud Console
GOOGLE_CLIENT_SECRET             # Google Cloud Console
GEMINI_API_KEY                   # Google AI Studio
NEO4J_BOLT_URL                   # neo4j+s://<auradb-id>.databases.neo4j.io
NEO4J_USERNAME                   # usually "neo4j"
NEO4J_PASSWORD                   # AuraDB password
CUTIEE_NOVNC_URL                 # filled in after the worker's first deploy, see section 6
```

**`cutiee-worker` secrets (provisional parity; unused at current runtime):**

```
DJANGO_SECRET_KEY                # any value; worker runs no Django process today
GEMINI_API_KEY                   # any value; worker makes no model calls today
NEO4J_BOLT_URL                   # any value; worker writes nothing to Neo4j today
NEO4J_USERNAME
NEO4J_PASSWORD
```

The `start-worker.sh` process in `Dockerfile.worker` launches only Xvfb, fluxbox, x11vnc, websockify, and Chromium; no Python runs on the worker, so these five credentials are not read at runtime. They are declared in `render.yaml` to unblock a future sidecar (a heartbeat writer, log forwarder, or browser-use wrapper) that would run Python inside the container and reach AuraDB directly. You have two defensible choices during sync:

- **Parity posture (default):** paste the same values you used on `cutiee-web`. Keeps the two services interchangeable if a future sidecar lands.
- **Minimal posture:** leave all five worker secrets blank, or delete the blocks from `render.yaml` entirely. Smaller blast radius if the worker env leaks; reintroduce when a sidecar actually needs them.

Note on `DJANGO_SECRET_KEY`: `render.yaml` sets `generateValue: true` on `cutiee-web`, which produces an opaque value the user does not directly read. Pasting "the same value" into the worker therefore requires first copying the web-service secret from Render's **Environment** tab (click the eye icon to reveal). If you prefer a readable shared value, change the web side to `sync: false` and paste your own random string into both services. Pick one posture and stick with it; mixing `generateValue` with cross-service parity is what makes this awkward.

No other env vars need dashboard entry. The blueprint sets every tunable (`CUTIEE_CU_MODEL`, `CUTIEE_MAX_COST_USD_*`, `CUTIEE_PROGRESS_BACKEND`, `CUTIEE_BROWSER_CDP_URL`, etc.) to its canonical value so the two services stay in sync automatically. If you need to override one, change it in `render.yaml` and push, not in the dashboard.

`DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` are set in the blueprint and additionally auto-include the Render hostname via `RENDER_EXTERNAL_HOSTNAME` detection in `cutiee_site/settings.py`. The settings module also sets `SECURE_PROXY_SSL_HEADER` and `SESSION_COOKIE_SECURE` whenever `RENDER_EXTERNAL_HOSTNAME` is present, which is required for OAuth callbacks to succeed behind Render's TLS terminator.

## 4. First-Time Blueprint Sync

1. Push `render.yaml` and `Dockerfile.worker` to `main`.
2. In Render: **New +** > **Blueprint** (or **Blueprints** > an existing one > **Sync**).
3. Connect the GitHub repo `github.com/Edward-H26/CUTIEE`, branch `main`.
4. Render lists the two services and their plans. Confirm Standard for both.
5. Render prompts for each `sync: false` secret. Paste the web-side secrets now; leave `CUTIEE_NOVNC_URL` blank for now (see section 6).
6. Click **Apply**. Render starts both builds in parallel. First builds run 6-8 minutes each because the worker pulls the Playwright base image plus noVNC + websockify apt packages, and the web service downloads Playwright's Chromium.

## 5. Why the Worker Needs No "Ports" Configuration

Render Web Services route public HTTPS traffic to exactly one container port, chosen by the `PORT` environment variable (or a fallback auto-detected from `EXPOSE` directives). `render.yaml` sets `PORT=6080` on `cutiee-worker`, so `https://<worker-hostname>.onrender.com/*` is routed to websockify, and `vnc.html` renders the live framebuffer.

Chromium's CDP on port 9222 stays reachable on the private network because the Dockerfile binds it to `0.0.0.0:9222` inside the container. Any service in the same Render workspace can reach `http://cutiee-worker:9222` regardless of what port is "public". That private address is exactly what `cutiee-web`'s `CUTIEE_BROWSER_CDP_URL` is set to.

No Networking / Ports / Additional Ports UI step is required. Earlier versions of this guide pointed at a settings tab that does not appear for Docker Web Services in the current Render UI; setting `PORT` in the blueprint supersedes it.

## 6. Wire `CUTIEE_NOVNC_URL` After the Worker's First Deploy

1. Wait for `cutiee-worker` to finish its first build and reach **Live**.
2. Copy the full public URL from the service header, for example `https://cutiee-worker-xyz.onrender.com`. The `-xyz` suffix is assigned by Render per workspace and cannot be predicted before the first deploy, which is why `CUTIEE_NOVNC_URL` is `sync: false` in the blueprint rather than hardcoded.
3. Open `https://cutiee-worker-xyz.onrender.com/vnc.html` directly. The noVNC viewer should load with a **Connect** button. Click it. A dark Xvfb desktop with a fluxbox taskbar confirms all five worker processes are healthy. No tasks are running yet, so Chromium may or may not have focus.
4. Back on `cutiee-web` > **Environment**, paste `CUTIEE_NOVNC_URL=https://cutiee-worker-xyz.onrender.com/vnc.html` into the prompt for the secret. Trigger **Manual Deploy**. ~3 minutes later the web service restarts with the env var populated.
5. Visit `https://cutiee-1kqk.onrender.com`, sign in with Google, submit a task, and watch the Tasks detail page. The main panel renders a card titled "Live browser" containing the noVNC iframe with autoconnect. You see the agent's Chrome in real time.

The iframe only appears when both conditions are met: `CUTIEE_NOVNC_URL` is set AND the active execution's status is `running`. Before a run starts or after it finishes, the panel shows other cards (preview approval, step log, cost summary).

## 7. Day-2 Changes

- **Changing a tunable** (`CUTIEE_CU_MODEL`, cost caps, etc.): edit `render.yaml`, push to `main`, Render auto-deploys both services with the new value.
- **Rotating a secret**: edit it in the Render dashboard on the service that owns it. Do NOT move it into `render.yaml` unless you commit to a value-not-secret contract.
- **Scaling the worker**: change `plan:` on `cutiee-worker` in `render.yaml`. Chromium + Xvfb are memory-bound, so more RAM is the first lever.
- **Scaling the web**: a plan bump alone does not add throughput because the blueprint pins `--workers 1 --threads 4` in `startCommand`. To serve more concurrent classmates, edit the start command to raise `--threads` (cheap, I/O bound) or `--workers` (expensive, Chromium-state bound), then optionally raise `plan` to give the new workers room. Threads scale Cypher round-trips and HTMX polls; workers scale concurrent CU runs. One CU run per classmate caps at one worker per active user.

## 8. Verification Checklist

```
[ ] Web service deploy succeeded: Render shows status "Live".
[ ] Worker service deploy succeeded: same.
[ ] https://cutiee-1kqk.onrender.com loads the landing page.
[ ] Google OAuth sign-in returns successfully.
[ ] https://<cutiee-worker-xyz>.onrender.com/vnc.html shows noVNC directly (use the full public hostname from the service header, not the private DNS name `cutiee-worker`).
[ ] Submit a task with a simple URL such as https://example.com.
[ ] The Tasks detail page shows the preview approval card.
[ ] After you approve, the "Live browser" iframe appears.
[ ] You can see Chromium load the page in the framebuffer.
[ ] Step rows populate in the table below the iframe every 2 seconds.
[ ] At completion, cost appears in the Cost dashboard.
[ ] Neo4j contains a new :Execution and chained :Step nodes.
```

If the iframe stays empty even though the worker URL works in isolation, the likely cause is the browser refusing to embed the worker's noVNC origin. Check, in this order:

1. **Try an incognito window with extensions disabled first.** Ad blockers and privacy extensions frequently block third-party iframes on sight and produce an empty frame with no console message; this rules out the easiest cause in 30 seconds.
2. Browser devtools **Console** in a normal window. A message like `Refused to frame '...' because it violates the following Content Security Policy directive: frame-ancestors ...` means the response carries a CSP that excludes `cutiee-web.onrender.com`. The shipped websockify and noVNC assets do not set CSP by default, so this is usually either a corporate middlebox injecting one or a custom header you added to the Dockerfile.
3. Browser devtools **Network** tab on the iframe request. A `200` with `X-Frame-Options: DENY` or `SAMEORIGIN` means the same thing from an older header; same remediation.
4. **Mixed content is rarely the cause on Render** because both services are HTTPS by default. If you customized the worker to a non-TLS port, switch back.

## 9. Rollback

Render keeps recent deploys. On a bad push to either service:

1. Service > Deploys tab.
2. Click a prior green deploy > Rollback.

Rollback takes 2-3 minutes. Neo4j migrations are additive so no database rollback is needed.

## 10. Cost

| Item | Monthly |
|------|---------|
| `cutiee-web` on Standard | $25 |
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
