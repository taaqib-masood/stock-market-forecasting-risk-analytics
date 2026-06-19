# Boro UI Dashboard Rebuild — Design Spec

**Date:** 2026-06-19
**Status:** Approved (design); pending implementation plan
**Workspace:** V-1.0 worktree (`../V-1.0`)

## Goal

Replace the current dark / space-navy / indigo-gradient look of `demo.html` with the
warm-minimalist **Boro UI** aesthetic (light theme only). Use Google Stitch to generate
every tab in the Boro design language, then port the generated markup back into a working,
chart-driven dashboard.

The dashboard is a single static HTML file (no backend, no build step): Tailwind via CDN,
Chart.js via CDN, Inter font, CSS-variable theming.

## Source design system

- **Stitch project:** `Remix of Buro Fintech App` — `projects/8092376236283519910`
- **Design system:** `Boro UI` (attached to the project; resolve exact `assets/<id>` via
  `list_design_systems` at implementation time).
- **Aesthetic tokens (Boro UI):**
  - Background: warm off-white `#FCF8F8` (cards `#FFFFFF`)
  - Primary: near-black `#080909` with white text
  - Accent: blue `#075CF2` (interaction / progress); green/red/orange for financial status only
  - Type: **Inter** throughout; hero numbers large with tight tracking (-0.02em to -0.04em)
  - Shape: high radius — buttons full/pill, cards 24px
  - Depth: **no drop shadows**; hairline `#E7E8EA` borders + tonal layering
  - Layout: 24px horizontal margins, 8px vertical rhythm, generous whitespace

## Scope

Rebuild all **13 tabs** in Boro style:
Sentiment (default), Technical, Macro, Screener, Moat, AI Explainer, Monte Carlo, Drift,
52 Features, FII/DII, India Signals, Watchlist, Zakat.

## Output

- New file: `V-1.0/demo-boro.html`.
- Original `demo.html` stays untouched until the user approves a swap.
- Light theme only — the existing dark/light toggle is dropped.

## Stitch generation plan

- One `generate_screen_from_text` call per tab (13 total).
- Params: `designSystem = assets/<Boro UI id>`, `deviceType = DESKTOP`, `modelId = GEMINI_3_1_PRO`.
- Each prompt describes that tab's actual content in Boro terms. Examples:
  - Monte Carlo: "Monte Carlo simulation results — fan/cone chart, percentile stat cards, VaR table"
  - Technical: "Technical analysis — price chart frame, indicator cards (RSI/MACD), signal table"
  - Watchlist: "Halal watchlist table — ticker rows, hairline separators, status chips"
- Generation is slow (minutes each). On timeout, **do not retry** — poll `get_screen` every
  ~30s (up to ~10 tries) per the tool's own guidance.

## Port architecture (the real work)

Stitch emits **static HTML + CSS only — no JS**. Porting steps:

1. **Build the shared shell once** (from the first generated screen):
   - Boro CSS token layer: rewrite `:root` to Boro colors/radius/spacing; keep Inter.
   - 13-tab pill nav in Boro style.
   - Reusable component classes: `card`, `stat` (hero number), hairline `table`, `chip`,
     `chart-frame`.
2. **Per tab:** extract the Boro visual structure (layout, cards, type scale, tables, chart
   *frames*) from the generated screen, then **re-attach the existing Chart.js instances and
   data-binding JS** from `demo.html` into those frames.
3. Chart.js theming is hand-matched to Boro tokens (grid lines, fonts, series colors) — Stitch
   does not know the existing chart configs.

## Risks (on record, accepted)

- 13 Stitch generations ≈ 30–60 min before porting begins.
- Chart.js styling must be manually aligned to Boro.
- Re-wiring JS per tab is the main bug surface — each tab is verified before moving on.

## Verification

- Open `V-1.0/demo-boro.html` in a browser.
- Walk all 13 tabs; confirm every chart and table populates with data.
- Confirm visual tokens match Boro (off-white bg, near-black primary, blue accent, pill
  buttons, hairline borders, no shadows, Inter).
- No automated tests — static file, no build/network step.

## Out of scope

- Dark theme / theme toggle (dropped).
- Backend or data-source changes.
- Mobile-specific layouts (Boro project is DESKTOP; dashboard stays desktop).
- Touching the Python signal/ML pipeline.
