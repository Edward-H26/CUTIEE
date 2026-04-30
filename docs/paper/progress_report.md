# CUTIEE Progress Report

## Design Representation

The wireframes are located at <https://www.figma.com/design/OgXcHPcNCz212XCgyI1oIp/CUTIEE?node-id=19-33&t=fClNVeoFqG4i6UB1-1>.

The prototype is located at <https://www.figma.com/proto/OgXcHPcNCz212XCgyI1oIp/CUTIEE?node-id=8-2&t=EfmPrJNcFxXub64D-1&scaling=min-zoom&content-scaling=fixed&page-id=0%3A1&starting-point-node-id=8%3A2>.

The deployed demo is located at <https://cutiee-1kqk.onrender.com/>.

The system workflow diagrams are located below. The first shows the production deployment topology across the Render web service, the Render Docker worker, and the Neo4j AuraDB single durable store. The second shows the per-task execution flow inside `apps.tasks.services.runTaskForUser` and `agent/harness/computer_use_loop.ComputerUseRunner.run`, including the eleven-step inner loop, the replay branches, and the post-run ACE memory pipeline.

### Deployment Topology

```
                         Classmate's browser
                               |          |
                    HTTPS      |          |  noVNC WebSocket
                    HTMX       |          |  (iframe, public URL)
                               v          v
   +---------------------------------+   +-------------------------------+
   | cutiee-web   (Render Python)    |   | cutiee-worker (Render Docker) |
   |                                 |   |                               |
   |   Django + HTMX                 |   |   Xvfb :99                    |
   |   allauth Google OAuth          |   |   fluxbox                     |
   |   ComputerUseRunner             |---|-> Chromium (headed)           |
   |   BrowserController (Playwright | CDP|  --remote-debugging=9222     |
   |       connect_over_cdp)         |9222|                               |
   |   CuClient (Gemini CU or        |   |   x11vnc :5901                |
   |        browser-use)             |   |   websockify :6080            |
   |                                 |   |       -> /usr/share/novnc    |
   |   Renders <iframe src=          |   |                               |
   |     $CUTIEE_NOVNC_URL>          |   |   (No Python runtime.         |
   |                                 |   |    Writes nothing to Neo4j.)  |
   +----------------+----------------+   +-------------------------------+
                    |
                    | Cypher over bolt+s://
                    v
    Neo4j AuraDB    (single durable store)
        :User, :Task, :Execution, :Step,
        :MemoryBullet, :AuditEntry, :Screenshot,
        :CostLedger, :ActionApproval, :PreviewApproval,
        :ProgressSnapshot, :UserPrompt
```

### Per-Task Execution Flow

```
User submits task
       |
       v
apps.tasks.services.runTaskForUser
       creates :Task, dispatches background thread
       |
       v
ComputerUseRunner.run(userId, taskId, taskDescription, executionId)
       |
       |- _resolveFragmentPlan  -->  FragmentPlan (may be empty)
       |
       |- _runPreviewAndAwaitApproval
       |     writes :PreviewApproval {status:"pending"} with the generated
       |     summary. HTMX dashboard polls and renders Approve / Cancel.
       |     If user cancels, state.markComplete("user_cancelled_preview")
       |     and return immediately without touching the browser.
       |
       |- browser.start  -->  Xvfb Chromium; VNC already streaming
       |
       |- if whole-template replayPlan found:    _executeReplay         (zero cost)
       |- elif prematchedNodes set:               _executePrematchedNodes (zero-cost prefix)
       |- elif initialUrl:                       _recordInitialNavigation
       |
       |- _runLoop(state, fragmentPlan)
       |     For each stepIndex in [current, maxSteps):
       |        > if fragment matches AND not requires_model_value:
       |            _executeFragment   (zero cost, approval on HIGH)
       |        > else:
       |            _executeOneStepWithRetry
       |               1. captcha_detector  -->  if hit, mark_complete
       |               2. injection_guard   -->  annotate risk on hit
       |               3. client.nextAction       (Gemini or browser-use)
       |               4. classifyRisk
       |               5. cost_ledger       -->  if over cap, mark_complete
       |               6. heartbeat.check   -->  if terminate, mark_complete
       |               7. approvalGate      -->  HIGH risk blocks
       |               8. browser.execute
       |               9. capture screenshot + redactor
       |              10. screenshotSink         (Neo4j 3-day TTL)
       |              11. auditSink              (:AuditEntry)
       |
       |- browser.stop  -->  tears down Xvfb + Chromium + VNC
       |
       L ACEPipeline.processExecution            (ONLY if not state.replayed)
              Reflector  -->  QualityGate >= 0.60  -->  Curator  -->  applyDelta
              refine() enforces maxBullets + per-type quota (60 / 25 / 15)
```

The presentation is located at <https://docs.google.com/presentation/d/1Jy5c47P6yIKCOJzFyEJeNSJSPlXOT5E196PbNhSSuYQ/edit?usp=sharing>.

## Current Progress

The pipeline described in the Final Feature Set and User Flow sections is implemented and operational. CUTIEE runs as a Django web application backed by a Neo4j graph database, and a user can complete the full loop by authenticating through Google, submitting a natural language task with an optional starting URL, reviewing the generated preview, approving or cancel it, and observing the agent work through an embedded browser view. The memory system records every successful trajectory as a reusable template and subsequent runs of the same task replay the matched actions at near zero inference cost. A safety classifier intercepts irreversible actions for a second explicit approval and a plan drift detector pauses the run and requests a revised approval whenever the observed page state diverges from a recorded template. The underlying agent runs on the Gemini Flash family, which is the first frontier grade model to expose computer use at flat Flash tier pricing and this choice accounts for the two orders of magnitude cost reduction reported in the Final Feature Set.

Four authenticated web surfaces expose the system to end users and stakeholders. A task submission page streams the live browser through an embedded viewer, so the operator can supervise each click in real time. A memory dashboard lists every learned template and supports one click stale marking, which allows a domain expert to retire workflows that no longer apply without touching the codebase. An audit trail page enumerates every action the system has taken for a given user, with on demand retrieval of the original screenshot and records persist long enough to cover typical review and export windows. A cost dashboard tracks live spend per task, per day, and per user, and an atomic wallet ledger terminates any run that would breach the configured daily ceiling. Together the cost ledger and the audit trail address the two operational constraints that regulated deployments place on any computer use agent: bounded spend and reviewable provenance.

## Future Plan

Our research roadmap centers on two technical tracks that together extend CUTIEE from a frozen model harness into an adaptive, self improving system: multi tier model routing and task specific fine tuning. Both tracks draw directly on the production data that the current deployment already captures, so execution does not depend on infrastructure beyond what is already in place.

**Multi tier model routing.** We will reintroduce the routing layer that was consolidated when Gemini Flash gained computer use capability at flat pricing, and we will ground the new router in measurements collected from production traffic. The target topology has three tiers with confidence based escalation between them. A small local model such as Qwen3 0.8B or ShowUI-2B runs on CPU and handles routine navigation, form completion, and high confidence click targets at near zero marginal cost. A compact specialist such as Fara-7B (Awadallah et al., 2025) handles moderately complex reasoning on a local GPU under four bit quantization at roughly $0.003 per call. A cloud frontier tier such as Gemini 3 Flash or Claude Sonnet handles ambiguous or high stakes actions at roughly $0.02 per call. A difficulty classifier trained on the audit trail will assign each candidate action to a tier based on observed features such as page complexity, risk class, and prior replay confidence, and the router will escalate whenever the chosen tier returns a confidence below a calibrated threshold. We will quantify cost accuracy trade off curves per task domain and release the classifier as an auxiliary artifact so that other groups can calibrate routing policies against their own model pools. This track builds directly on the adaptive routing results of Liu et al. (2026), who report a 78 percent inference cost reduction at a two point accuracy cost when routing replaces a single backend agent.

**Task specific fine tuning.** The replay template library that CUTIEE accumulates during normal operation is itself a structured supervised learning signal, since every procedural bullet encodes a (task description, page state, action) triple with a success label implied by the fact that the original trajectory completed. We will exploit this signal in three phases that feed back into the routing tiers above. In the first phase we will fine tune an open weight base model such as Qwen3 0.8B on the procedural bullets collected from all users, which produces a routing aware small model specialized for CUTIEE's action grammar. LoRA adapters will keep the fine tuning cost bounded and will allow per tenant customization without retraining from scratch. In the second phase we will fine tune Fara-7B on the same corpus enriched with the full Reflector commentary, so that the specialist tier internalizes the corrections and quality gates that the ACE pipeline applies in production. In the third phase we will add a continual learning loop that converts user approval and rejection decisions into preference pairs and updates the fine tuned checkpoints through a lightweight online method such as DPO or KTO. Domain specific fine tuning for healthcare, finance, and enterprise SaaS will follow once a tenant accumulates sufficient template volume, typically measured in the low thousands of successful trajectories.

As a result, the router directs traffic to the cheapest tier that can succeed, the success signal populates the fine tuning corpus, and the fine tuned small and specialist models progressively absorb action classes that currently escalate to Flash. We expect the steady state cost per task to drop below the present $0.004 as the fine tuned tiers cover more of the action space, and we plan to report measured savings against the Flash only baseline on the three standard web agent benchmarks (Mind2Web, WebArena, OSWorld) during the ICML camera ready period.
