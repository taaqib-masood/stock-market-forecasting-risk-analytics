# Boro UI Dashboard Rebuild — Design Spec

**Date:** 2026-06-19
**Status:** Approved (design); pending implementation plan
**Workspace:** V-1.0 worktree (`../V-1.0`)

## Goal

Replace the current dark / space-navy / indigo-gradient look of `demo.html` with the
**Boro Portfolio** institutional-analytics aesthetic (light theme only). Use Google Stitch
to generate every tab in the Boro Portfolio design language, then port the generated markup
back into a working, chart-driven dashboard.

The dashboard is a single static HTML file (no backend, no build step): Tailwind via CDN,
Chart.js via CDN, Inter font, CSS-variable theming.

## Source design system

- **Stitch project:** `Remix of Buro Fintech App` — `projects/8092376236283519910`
- **Design system:** `Boro Portfolio` — `assets/59f0dfadbf494ce7a086096f05e92391` (version 2).
  Chosen over the project's `Boro UI` theme because Boro Portfolio is purpose-built for a
  "high-density investment analytics platform (Bloomberg Terminal × Notion), Light Mode" —
  the exact shape of this app. Boro UI is a consumer-payments aesthetic that fights dense tables.
- **Aesthetic tokens (Boro Portfolio):**
  - Background (Level 0 canvas): cool near-white `#f7f9fd`
  - Surfaces (Level 1 cards/sidebar): `#ffffff` with 1px `#c0c7cd` (outline-variant) borders
  - Primary: slate blue `#487d9a` (interactive/brand); darker `#2d6480` for emphasis
  - Status: green / amber / red `#ba1a1a` strictly for performance + risk indicators
  - UI type: **Geist** (headline-lg 30px/600 down to body-sm 12px)
  - Data type: **JetBrains Mono** for ALL numbers, tickers, tabular figures (data-lg 18px → data-sm 12px)
  - Labels: `label-caps` — Geist 11px/700, 0.05em tracking, uppercase, for table headers + metadata
  - Shape: disciplined "soft-square" — global radius `0.25rem` (4px); chips slightly higher; **no pills**
  - Depth: tonal layers + 1px outlines, **no heavy shadows**; hover = border/tint shift, no lift
  - Layout: fixed 240px left sidebar + 12-col content grid; compact 8px table rows; 4px/8px spacing
  - Charts: 1.5px line stroke, slate blue main series, muted grey gridlines

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
- Params: `designSystem = assets/59f0dfadbf494ce7a086096f05e92391`, `deviceType = DESKTOP`,
  `modelId = GEMINI_3_1_PRO`.
- Each prompt describes that tab's actual content in Boro terms. Examples:
  - Monte Carlo: "Monte Carlo simulation results — fan/cone chart, percentile stat cards, VaR table"
  - Technical: "Technical analysis — price chart frame, indicator cards (RSI/MACD), signal table"
  - Watchlist: "Halal watchlist table — ticker rows, hairline separators, status chips"
- Generation is slow (minutes each). On timeout, **do not retry** — poll `get_screen` every
  ~30s (up to ~10 tries) per the tool's own guidance.

## Port architecture (the real work)

Stitch emits **static HTML + CSS only — no JS**. Porting steps:

1. **Build the shared shell once** (from the first generated screen):
   - Boro Portfolio CSS token layer: rewrite `:root` to Boro Portfolio colors/radius/spacing;
     load Geist (UI) + JetBrains Mono (data) fonts; replace Inter.
   - Fixed 240px left sidebar holding the 13 tabs (replaces the current top pill nav);
     collapses to a top bar under 768px.
   - Reusable component classes: `card` (Level 1 + 1px border), `stat` (JetBrains Mono figure +
     `label-caps` caption), compact hairline `table`, status `badge`, `chart-frame`.
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
- Confirm visual tokens match Boro Portfolio (cool near-white `#f7f9fd` bg, slate blue
  `#487d9a` accent, Geist UI text, JetBrains Mono numbers, 4px soft-square corners, 1px
  hairline borders, no heavy shadows, 240px sidebar nav).
- No automated tests — static file, no build/network step.

## Out of scope

- Dark theme / theme toggle (dropped).
- Backend or data-source changes.
- Mobile-specific layouts (Boro project is DESKTOP; dashboard stays desktop).
- Touching the Python signal/ML pipeline.
