# Memoria Design System

Design system for **Memoria** — a B2B platform that gives every employee in small and mid-sized companies their own personal AI agent. Agents learn how each person works (procedural memory, not chat history), and — uniquely — talk to each other agent-to-agent with a human in the loop, so a team keeps moving when someone is out.

The product surface is a web app (Django + Tailwind v4) with a calm, "glassy" aesthetic: a single slate-blue accent (`#6C86C0`), a signature pastel aurora background, and generous use of frosted-glass cards (`rgba(255,255,255,.55)` over `backdrop-filter: blur(20px)`). Type pairs **Manrope** (display, extrabold) with **Inter** (body).

---

## Sources

Everything in this system was distilled from one source:

| Source | Reference |
|---|---|
| Codebase | `Edward-H26/MIRA` (GitHub, `main` @ `c38f2127…`) — Django app, see `app/memoria/`, `static/css/base.css`, `static/memoria/landing.css`, `templates/memoria/landing.html`, `templates/memoria/home.html` |
| Product copy | Pitch script provided by founder (14 slides, see `slides/README.md`) |

Key imports landed in this project under `static/`, `templates/memoria/`, `css/`, `images/` — the originals are kept for traceability; **working assets live in `assets/`** and tokens in `colors_and_type.css`.

---

## Index

- `README.md` — this file
- `colors_and_type.css` — colour + type tokens (all `--mm-*` CSS variables)
- `SKILL.md` — agent-skill entry point
- `assets/` — logos, icons, integration marks (SVG)
  - `logo.svg`, `icon-edit.svg`, `icon-memory.svg`, `sidebar-bg.svg`, `google.svg`
  - `integrations/` — Slack, Notion, GitHub, Gmail, Google Calendar, Discord, Telegram, WhatsApp
- `preview/` — design-system preview cards (rendered in the Design System tab)
- `ui_kits/web-app/` — React UI kit for the Memoria web app (sidebar, composer, message list, memory viewer, agent cards, auth modal)
- `slides/` — pitch-deck sample slides (16:9), built from the provided script
- `static/`, `templates/`, `css/`, `images/` — raw imports from the MIRA repo (kept as reference; do **not** ship from here)

---

## CONTENT FUNDAMENTALS

**Voice.** Calm, plainspoken, pragmatic. Memoria talks to knowledge workers, not engineers. It sounds like a thoughtful coworker, never a marketer. No hype words ("revolutionary," "game-changing"), no slogans.

**Person.** Mostly **second person** — "your AI memory," "what would you like to do?", "Have natural conversations with an AI that remembers context." First-person plural ("we," "us") appears only in the pitch narrative and in team-facing copy. Never "I."

**Tone.** Declarative, short. Hero copy is one sentence of benefit, followed by one sentence of specifics. Example from the landing: *"Your AI memory, organized and accessible. Capture, retrieve, and build on your knowledge with AI-powered memory and intelligent multi-agent conversations."*

**Casing.**
- Headlines: **Sentence case** ("Your AI memory, organized and accessible"). Never title case.
- Buttons: **Title Case or sentence case, two words max where possible** — "Start for free", "Sign in", "Go to app", "Create Group", "Join Group".
- Section labels / eyebrows: **UPPERCASE** with 1.5px tracking — "AFFILIATED WITH", "YOUR GROUPS", "RECENT CHATS".
- Form placeholders: sentence with ellipsis — "Group name…", "Paste invite key…".

**Word choices.**
- **Agent** (not assistant, not bot). "My Agent", "Kevin's agent."
- **Memory / memories** as a countable object the user can rate and edit.
- **Skills** as capabilities an agent acquires.
- **Group** or **Project group** (not channel, not workspace) for multi-person collaboration spaces.
- **Chat / conversation** interchangeably for 1-on-1 with your own agent.

**What we *don't* do.**
- No emoji in product UI. The only pictographs are line-weight SVG icons and brand logomarks. (Emoji may appear in user-generated content only.)
- No exclamation points in system copy.
- No "Oops!" / cutesy empty states. Empty states state the fact: *"No chats yet. Tap + New Chat to start one."*
- No jargon in onboarding. The pitch uses "agent-to-agent collaboration"; the product UI just calls it "Groups".

**Examples from the product:**
- Landing pill: *"Memory-augmented AI, live for everyone"*
- Feature: *"Search across your memories and documents with meaning-based retrieval, not just keywords."*
- Home greeting: *"Welcome to Memoria — What would you like to do?"*
- Mobile empty state: *"No chats yet. Tap + New Chat to start one."*

---

## VISUAL FOUNDATIONS

**Core motif — the Aurora.** Every authenticated screen and the landing page sit on a *fixed* (`background-attachment: fixed`), pastel radial-gradient wash: pink in the top-right (~85%/12%), blue in the mid-left (~15%/40%), lavender in the bottom-right (~82%/85%), tinting a 135° linear gradient from `#e9f0fc → #e6dff0`. It is the brand's most identifiable visual element — everything else is built to sit *on top* of it as frosted glass.

**Material — frosted glass.** Cards, nav bars, the sidebar, modals, and popovers use white at 55–70% opacity over `backdrop-filter: saturate(150%) blur(20px)`, with a 1px `rgba(255,255,255,.55)` border. There is no solid-white surface in the chrome — the aurora is meant to show through at all times. When you need higher contrast (forms, dense lists), step up to `rgba(255,255,255,.7)` and keep the blur.

**Colour vibe.** Cool, low-chroma. A single accent — `#6C86C0` slate-blue — drives every CTA, link, focus ring, active-nav state, and icon-on-tint. Hover is a slightly darker `#5A74AD`; active is `#4A6399`. No secondary accent. No rainbow charts — even data uses a monochrome ramp of the primary.

**Type.** Display = **Manrope** (600/700/800), tight tracking (−0.025em), set in a gradient clip on heroes; body = **Inter** (400/500/600/700), no tracking change. A little bit of weight-contrast (800 hero against 400 subhead) carries most of the hierarchy; we don't vary colour or size to substitute for weight.

**Spacing.** Tailwind-aligned 4px base unit. Cards breathe: 24–32px internal padding is default; 48–80px vertical rhythm between sections. Hero sections lead with `pt-32` (128px) top padding. Nothing is tight — even buttons are `py-2.5 / py-3.5` with 44px min-hit-target.

**Corner radii.** 4 / 8 / 12 / **16 / 20** px. The brand's "signature" radius is 16–20px: feature cards, logo tiles, the status pill, buttons on hero CTAs. Inputs are 8–10px. Pills/avatars are fully round (`9999px`). Never 2px or 24+px.

**Buttons.**
- Primary ("cta-gradient"): solid `#6C86C0`, white text, 10px radius, `shadow 0 4px 12px rgba(108,134,192,.18)`. Hover: `#5A74AD` + `shadow 0 8px 20px …` + `translateY(-1px)`. Active: `#4A6399` + `scale(.97)`.
- Ghost ("cta-ghost"): 70% white glass over aurora, 1px white/70 border, body-dark text.
- Secondary: solid white, 1px `#E5E7EB` border, dark text.
- Text/ghost icon: transparent, `#6B7280` icon that swings to primary on hover with a 50%-white pill background.

**Hover / press states.** Hover = *either* a 1–2px `translateY(-1px/-2px)` lift + larger shadow, *or* a background-colour step (white glass → white). Press = `scale(.97)` with reduced shadow. Cards lift, buttons press. Icons don't scale.

**Borders.** Glass surfaces use `rgba(255,255,255,.55)` 1px; solid surfaces use `#E5E7EB`. A 2px inner ring appears only on avatar buttons (to keep them legible over the aurora).

**Shadows.** Six elevations, all with a *blue* tint (`rgba(108,134,192,*)`) not neutral black — this ties the lift to the accent. No hard black shadows anywhere.

**Transparency & blur.** Used aggressively: header, sidebar, cards, modals, dialog backdrops. When not on glass, we fall back to `#ffffff` or `#fdfdfd` (slightly warm white) — never pure grey.

**Imagery.** No photography in the existing codebase. The brand uses only (a) line-weight SVG icons, (b) institution crests at 80×80 rounded tiles with a gentle float animation (`transform: translateY(-6px)`, 3.6s ease-in-out), and (c) integration logos on rounded tiles. If imagery is ever added, it should be cool-toned, softly lit, and avoid warm/orange casts that fight the aurora.

**Animation.** Subtle and short. All interactive transitions are `150–300ms` with `cubic-bezier(.4, 0, .2, 1)` (Tailwind default). Signature moves: the logo-tile *float* (±6px, 3.6s ease-in-out, infinite); the status dot *pulse* on the landing pill; thinking-dots *bounce* in chat (1.4s, stagger 0.16s). No bouncy overshoots, no long page transitions, no Lottie.

**Layout rules.** Fixed desktop header at 64px; left nav at 229px. Content is centred in a `max-width: 6xl (72rem)` container with `px-4 sm:px-6 lg:px-8`. Everything scrolls inside `.scroll-container` with a 4px-wide translucent scrollbar. Mobile collapses the sidebar into a bottom nav.

**What to avoid.**
- Bluish-purple gradients on buttons (the CTA is flat, not gradient — only text and tile backgrounds gradient).
- Pure `#000` shadows.
- Warm accents (oranges, ambers) — they fight the aurora.
- Heavy drop-shadows on glass.
- Outlined icons at mixed stroke weights — always 2px.

---

## ICONOGRAPHY

Memoria's icon system is **feather-style line SVGs at 2px stroke, 24×24 viewBox**. The codebase renders them inline in templates (see `landing.html`, `home.html`) rather than using an icon font — every icon is a hand-rolled `<svg>` with `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`. The silhouettes match the **Feather** / **Lucide** set exactly (message-square, search, file-text, link, users, plus, log-in, arrow-right), so the easiest way to extend is to pull from [Lucide](https://lucide.dev) at the same stroke weight.

**Sizing.**
- Nav-rail icons: 20×20.
- In-card feature icons: 20×20 set inside an 11×11 (44×44) tinted tile with `rounded-xl` (12px) and the primary colour.
- Inline-with-text icons: 14–16, matching cap-height.
- Status-dot / decorative: 8×8 filled circle.

**Colour.**
- Default: `#6B7280` (muted).
- Active / hover / on-tint-tile: `#6C86C0` (primary) or white (when the tile itself is primary-filled).
- Icons *never* carry their own colour — they inherit `currentColor`.

**Brand marks in `assets/`:**
- `logo.svg` — the 3-circle Memoria logomark (`#4D58F0`), 43×40. Used alongside the "Memoria" wordmark (Manrope 800, −1px tracking, gradient-clipped in `#6C86C0 → #6C86C0`).
- `icon-memory.svg`, `icon-edit.svg` — custom in-product glyphs.
- `google.svg` — Google G, used in the OAuth "Sign in with Google" button.
- `sidebar-bg.svg` — tiny decorative SVG used as sidebar background.
- `integrations/*.svg` — Slack, Notion, GitHub, Gmail, Google Calendar, Discord, Telegram, WhatsApp (full-colour vendor marks; never recolour).

**Emoji.** Not used in product chrome. Allowed only in user-generated content (chat messages). Status is conveyed by a coloured dot, not 🟢/🔴.

**Unicode as icon.** Rare. Only the arrow chevron "›" appears as plain text in breadcrumbs. Otherwise, everything is an SVG.

**Substitutions flagged.** There are **no custom font files shipped** — the system depends on Google Fonts (Manrope, Inter) loaded at runtime. If you need offline fidelity, grab the .ttf/.woff2 from Google Fonts and drop them into `fonts/` (not created yet — flag to user).

---

## Caveats & asks

- **Fonts are CDN-only.** Manrope + Inter load from Google Fonts via `<link>`. No TTFs exist in the repo. If you want fully offline mocks, send me the .woff2 files.
- **No photography / illustration** exists in the source. If marketing imagery is needed, we'll have to source or commission it; the aurora gradient is the only "brand artwork."
- **Logomark is literal three circles.** Fine as a mark, but a wordmark + monogram treatment would strengthen recognition — let me know if you'd like me to propose variants.
- **One product surface.** The MIRA repo is a single Django web app. No mobile or marketing-site split, so the UI kit covers web only.

**What I need from you to make this perfect:**
1. Confirm the **brand name** — the repo is "MIRA" but every user-facing string says **Memoria**. I used *Memoria* throughout. Good?
2. Drop in **font files** if you want offline-capable exports.
3. Tell me if there are **real product screenshots** of the chat + memory views I should match more tightly, or if the recreations in `ui_kits/web-app/` match your intent.
4. Should the pitch-deck `slides/` use the same calm palette, or do you want a bolder investor-deck variant?
