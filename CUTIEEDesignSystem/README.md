# CUTIEE Design System

**CUTIEE** — Computer Use agentIc-framework with Token-efficient harnEss Engineering. A B2B platform that automates employee operational and self-service tasks while navigating legacy enterprise systems to collect compliance evidence and verify controls.

This design system captures CUTIEE's visual language so new surfaces (marketing sites, dashboards, decks, prototypes) stay consistent with the shipping product. The visual system is shared with (and derived from) the sister project **MIRA / MEMORIA** — a self-evolving agentic framework with user-controlled memory — and both use the same primary palette, fonts, and glass-surface treatment.

## Sources

Inputs used to build this design system (readers may not have access — noted for provenance):

- **CUTIEE codebase** — `https://github.com/Edward-H26/CUTIEE` (Django). Canonical tokens: `static/css/cutiee.css`. Templates: `templates/base.html`, `apps/landing/templates/landing/landing.html`, `apps/tasks/templates/tasks/*.html`, `apps/memory_app/templates/memory_app/list.html`, `apps/audit/templates/audit/list.html`.
- **MIRA codebase** — `https://github.com/Edward-H26/MIRA` (the visual progenitor). Referenced: `static/css/base.css` (primary blue `#6C86C0`, glass surfaces, Inter), `static/images/logo.svg`.

Original `cutiee.css` preserved in `reference/cutiee_original.css` for future edits.

## Products

CUTIEE has a single web product with four surfaces:

1. **Landing** (`apps/landing/`) — marketing hero with features + cost strip.
2. **Tasks** (`apps/tasks/`) — submit tasks, watch HTMX-streaming executions, inspect per-step tier/cost/risk.
3. **Cost Dashboard** (`apps/tasks/dashboard`) — metric grid, daily spend line chart, tier distribution doughnut.
4. **Memory** (`apps/memory_app/`) — ACE bullets + procedural templates with strength bars.
5. **Audit** (`apps/audit/`) — immutable per-action log with risk + approval columns.

The UI kit in `ui_kits/web/` recreates these surfaces as clickable JSX components.

---

## Content Fundamentals

CUTIEE's voice is **quietly technical**: confident about the engineering, calm about the claims. It respects a reader who already knows what a VLM is but still explains the why. **MIRA/Memoria** is slightly warmer (consumer-facing AI assistant); CUTIEE is the enterprise-cost twin.

**Voice & tone**
- **Direct, declarative, lowercase-hinting.** "Your computer use agent, at $0 per recurring task." No exclamations. No "Welcome!", no "Let's go 🚀".
- **Numbers carry the rhetoric.** "~$0.30/task → ~$0.004/task · 98.7% reduction". Quantify everything; never say "much cheaper" when you can say "98.7% cheaper".
- **Second person, sparingly.** "Your agent gets smarter and cheaper over time." Not "I will…". Addresses an operator/engineer, not an end-user consumer.
- **Casing:** Sentence case everywhere — page titles, section heads, buttons. `Submit task`, `View cost dashboard`, `Run task now`. UPPERCASE only on `.cutiee-pill` (tracking 0.5px) and `.cutiee-divider span`.
- **Product name:** `CUTIEE` in all-caps when standalone; brand mark is the gradient wordmark. Never "Cutiee" or "cutiee".
- **Technical honesty:** status strings expose reality — `Warming up Qwen3.5 0.8B…`, `Checking model status…`, `Tier T2 (gemini-flash-lite)`. Don't hide the machine.
- **Tips are tips, not magic.** "Tip: paste a Google Sheets URL and ask CUTIEE to sort, sum, or rename a column." Concrete examples over abstract capability claims.
- **No emoji** in product copy. Unicode arrows allowed (`←`, `→`, `▾`) and a single pulsing `•` live-status dot. Decorative icons are stroked SVG only.
- **Empty states are plain-spoken.** "No tasks yet. Submit your first task above to see CUTIEE in action." Not "✨ Your journey begins…".

**Concrete examples (lift these patterns verbatim)**

> **Hero headline**: "Your computer use agent, at $0 per recurring task."
> **Hero sub**: "CUTIEE replays learned workflows, prunes stale context, and routes each action to the cheapest viable model, so your agent gets smarter and cheaper over time."
> **Feature card**: "Procedural Memory Replay — Every completed task becomes a zero-cost template. Recurring work drops to $0."
> **Cost strip**: "Gemini-only baseline: ~$0.30/task · CUTIEE hybrid: ~$0.004/task · 98.7% reduction"
> **Submit CTA**: "Submit task" (not "Get Started", not "Try CUTIEE Free")
> **Status banner**: "Checking model status…" / "Warming up Qwen3.5 0.8B…"

---

## Visual Foundations

**Color.** One primary blue `#6C86C0` carries 95% of the UI; a single linear gradient to violet `#8B6CC0` is reserved for the wordmark, primary CTA fills, feature-card icon tiles, and gradient text in headlines. A magenta accent `#CF6CC0` appears only on high-risk approval cards — it's a signal color, not a decoration. Backgrounds are a soft multi-radial aurora of pink-peach (`#ffe4f1`), blue (`#e0ecff`), and lilac (`#f3e9ff`) over an off-white base (`#f8fafc → #eef2f7`). The aurora is **fixed-attachment**, desaturated, and always behind glass — it sets mood, never competes.

**Type.** Two families. `Manrope` 600/700/800 for display (h1–h4, brand wordmark, hero headline with letter-spacing `-2px`). `Inter` 400/500/600/700 for everything else. `JetBrains Mono` for IDs, costs, step counts, timestamps (any number that needs to line up). Fluid type: hero `56px` → `40px` at ≤640px. Body 14–15px; small/meta 12px; uppercase micro-labels 11px with `0.5px` tracking. Headings are `font-weight: 800` with `letter-spacing: -1px` at h1 — tight, modern, not aggressive.

**Spacing.** 4px base (`--cutiee-space-1…8` = 4/8/12/16/24/32/48/64). Cards use `24px` padding (`--cutiee-space-5`), tight cards `16px`. Content width caps at `1100px` with `32/48px` horizontal padding. Vertical rhythm between sections is `48px`.

**Backgrounds.** Aurora gradient on `body`, always. No full-bleed imagery. No hand-drawn illustrations. No repeating patterns. No textures or grain. No dark-mode variant in production — the app is light-only by design. Glass surfaces sit on top and carry the content.

**Glass surfaces.** The signature move. Every card, sidebar, header, modal: `background: rgba(255,255,255,0.55)`, `backdrop-filter: blur(20px) saturate(150%)`, `border: 1px solid rgba(108,134,192,0.18)`, `border-radius: 16px`. Strong-glass variant (`0.70` opacity) for elements that need more contrast (inputs, menus). Never stack two glass panels on each other — the aurora shows through one pane of glass, that's the whole idea.

**Animation.** Calm and functional. All transitions `120–200ms` with `cubic-bezier(0.4, 0, 0.2, 1)`. Buttons `translateY(-1px)` on hover, never rotate or skew. A `1.6s ease-in-out infinite` `cutiee-pulse` keyframe (opacity + scale) on status dots and the `thinking-dots` bounce loader. No parallax, no scroll-triggered reveals in-app (landing page uses GSAP sparingly). Respect `prefers-reduced-motion`.

**Hover states.** Buttons: lift `-1px` + deeper shadow (`--cutiee-shadow-md → --cutiee-shadow-lg`). Ghost buttons: background `rgba(255,255,255,0.85)`. Nav links: `color: var(--cutiee-text)` + `background: rgba(108,134,192,0.12)`. Never use a different hue on hover.

**Press/active states.** Primary button: `transform: scale(0.97)`, background deepens to `#4A6399`, shadow softens. Feedback is subtle; the agent is long-running, the UI shouldn't bounce.

**Borders.** Always `1px solid`. Two variants: `rgba(108,134,192,0.18)` (default) and `rgba(108,134,192,0.32)` (strong, for emphasis or dashed empty-states). Hairline neutral `#E5E7EB` only on form-input dividers.

**Shadows.** Three levels, all **tinted with the primary blue** instead of black (`rgba(108, 134, 192, 0.10/0.18/0.22)`). This is what makes the glass feel like the product's glass. Never use black shadows.

**Corner radii.** `8 / 12 / 16 / 20 / 999` (pill). Cards `16px`, buttons `12px`, inputs `12px`, pills/badges `999px`. Never `4px` for interactive elements.

**Transparency & blur.** Backdrop-blur only on glass surfaces and on the page overlay behind modals (`rgba(0,0,0,0.20)` + `blur(4px)`). Never blur text, images, or icons. Sidebar/header use `blur(20px)` + `0.60` opacity; overlays use `blur(3–4px)` + `0.20–0.35` opacity.

**Imagery vibe.** Cool, desaturated, generous whitespace. If photos appear, prefer neutral/cool grading (no warm orange). Most of the product uses no photography — charts, tables, and glass cards do the work.

**Cards.** `.cutiee-card` = `backdrop-filter: blur(20px)` + `rgba(255,255,255,0.55)` + `1px solid rgba(108,134,192,0.18)` + `border-radius: 16px` + `24px` padding. A tight variant drops padding to `16px`. Feature cards lift on hover: `translateY(-4px)` + `--cutiee-shadow-lg`. Approval cards take a magenta-tinted border and a soft outer glow ring to signal attention without alarm.

**Layout rules.** Sticky 64px header (glass). Sidebar 229px (glass, optional). Main content flows in a 1100px column. On mobile the sidebar collapses to a drawer and a 5-tab bottom nav (glass) appears. Fixed elements: header and mobile bottom nav only.

**Density.** Medium-low. Most screens are cards on an aurora; tables are the exception (Audit, Task steps) — there, rows get `12/16px` cell padding and monospace type for numeric columns.

---

## Iconography

**Approach: minimal, stroke-based SVG, currentColor.** CUTIEE's templates use almost no icons — the brand is typographic, numeric, and glass-first. Where icons appear, they are single-path stroked glyphs at `stroke-width: 2`, `stroke-linecap: round`, `stroke-linejoin: round`, sized `20×20` (nav/header) or `16×16` (inline). They use `stroke: currentColor` so tint follows context.

**What's shipped in the codebase:** the feature grid uses single-letter tile glyphs (`P`, `T`, `S`, `M`) in a gradient-filled `44×44` rounded square — literal typographic "icons" over decorative SVG. That choice is intentional and extends to docs: prefer a letter or a number over a symbol when the concept is abstract ("Procedural memory", "Temporal pruning").

**Standards**
- **Icon library of choice:** [Lucide](https://lucide.dev) — load from CDN (`https://unpkg.com/lucide@latest`) for any surface that needs more than the shipped glyph set. Stroke weight, terminals, and 24×24 grid align with our letter-tile language. **Flagged substitution:** CUTIEE's codebase has no production icon set; Lucide is the closest-match CDN option and is used throughout this design system's previews.
- **SVGs used in this system** (copied, tintable via `currentColor`):
  - `assets/logo.svg` — gradient wordmark
  - `assets/logomark.svg` — `C`-in-gradient-square app icon
  - `assets/icon-replay.svg` — procedural memory replay
  - `assets/icon-prune.svg` — recency pruning
  - `assets/icon-route.svg` — multi-model routing
  - `assets/icon-audit.svg` — audit log
- **No icon fonts.** No `<i class="fa-…">`.
- **No emoji.** Not in product copy, not in icon tiles, not in empty states.
- **Unicode as UI glyphs:** yes, sparingly — `←` back link, `→` "Next" pagination, `▾` disclosure chevron.
- **PNGs:** not used. The only production PNG reference is the MIRA logomark mask, not carried over.

---

## Index

Files in this design system (root of project):

- `README.md` — this file.
- `colors_and_type.css` — all tokens + semantic element styles. Import first.
- `SKILL.md` — agent-invocable skill description.
- `reference/cutiee_original.css` — unmodified source-of-truth from CUTIEE repo.
- `assets/` — logo, logomark, SVG icons (currentColor).
- `preview/` — small HTML cards that populate the Design System tab.
- `ui_kits/web/` — interactive recreation of CUTIEE's web surfaces (landing → tasks → dashboard → memory → audit). Entry: `ui_kits/web/index.html`.

To use in a new design, link `colors_and_type.css` and copy assets from `assets/`. For component recipes, open `ui_kits/web/index.html` and lift JSX.
