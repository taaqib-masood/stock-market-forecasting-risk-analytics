# Boro Portfolio Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the 13-tab stock dashboard into the Boro Portfolio institutional-analytics look (light only) by generating each tab in Google Stitch and grafting the visual layer onto the existing working dashboard.

**Architecture:** `demo-boro.html` starts as an exact copy of `demo.html` (so all Chart.js + data JS keeps working). We then (a) swap the CSS token layer + top nav for Boro Portfolio tokens + a 240px sidebar, and (b) per tab, replace the inner markup with the Stitch-generated Boro structure and re-bind the existing canvas IDs / data hooks. Stitch defines the *look*; the existing file supplies the *behavior*.

**Tech Stack:** Single static HTML file. Tailwind (CDN), Chart.js (CDN), Geist + JetBrains Mono (Google Fonts). Google Stitch via MCP. Playwright (MCP) for visual verification. No build step, no backend.

## Global Constraints

- Work exclusively in the **V-1.0 worktree** (`../V-1.0`). Never touch the main checkout.
- Output file: `V-1.0/demo-boro.html`. Leave `V-1.0/demo.html` untouched.
- Light theme only — drop the dark/light toggle.
- Stitch project: `8092376236283519910`. Design system: `assets/59f0dfadbf494ce7a086096f05e92391`. `deviceType=DESKTOP`, `modelId=GEMINI_3_1_PRO`.
- Stitch generation is slow (minutes). On timeout, DO NOT retry the generate call — poll `get_screen` every ~30s, up to ~10 tries.
- Commits: targeted pathspec commits only (`git commit <path> -m …`) — the V-1.0 index has unrelated staged work that must not be swept in.
- Tabs (canvas/content order): Sentiment (default), Technical, Macro, Screener, Moat, AI Explainer, Monte Carlo, Drift, 52 Features, FII/DII, India Signals, Watchlist, Zakat.
- Verification is visual, not unit tests: load `file://…/demo-boro.html` in Playwright, switch tab, screenshot, confirm charts + tables populate and tokens match Boro Portfolio.

---

## Task 1: Scaffold demo-boro.html + reference capture

**Files:**
- Create: `V-1.0/demo-boro.html` (copy of `demo.html`)
- Create: `V-1.0/stitch-screens/` (raw Stitch output, reference only)

**Interfaces:**
- Produces: a working baseline identical to `demo.html` that later tasks restyle in place.

- [ ] **Step 1: Copy the file**

```bash
cd "../V-1.0" && cp demo.html demo-boro.html && mkdir -p stitch-screens
```

- [ ] **Step 2: Baseline screenshot (proves the copy works before we change anything)**

Use Playwright MCP: `browser_navigate` to `file://<abs>/V-1.0/demo-boro.html`, then `browser_take_screenshot` (full page). Expected: renders identical to current demo.html (dark/indigo), Sentiment tab active.

- [ ] **Step 3: Commit**

```bash
cd "../V-1.0" && git add demo-boro.html && git commit demo-boro.html -m "feat(ui): scaffold demo-boro.html from demo.html"
```

---

## Task 2: Generate + capture all 13 Stitch screens

**Files:**
- Create: `V-1.0/stitch-screens/01-sentiment.html` … `13-zakat.html`

**Interfaces:**
- Produces: 13 reference HTML files containing Boro Portfolio markup, one per tab.

- [ ] **Step 1: Generate each screen** — one `generate_screen_from_text` per tab, all with `designSystem=assets/59f0dfadbf494ce7a086096f05e92391`, `deviceType=DESKTOP`, `modelId=GEMINI_3_1_PRO`, `projectId=8092376236283519910`. Prompts (each prefixed *"Desktop dashboard tab for a stock analytics app, 240px left sidebar already present, light mode, dense:"*):

  1. Sentiment — "news sentiment: FinBERT score gauge, headline list with bull/bear chips, sentiment-over-time line chart"
  2. Technical — "technical analysis: price line chart, RSI + MACD indicator cards, signal table (BUY/HOLD), support/resistance stats"
  3. Macro — "macro overview: FRED indicator cards (rates, CPI, GDP), correlation heat strip, VIX line chart"
  4. Screener — "stock screener: filter bar, results table of tickers with score/PE/sector columns, compact rows"
  5. Moat — "competitive moat: per-company moat score radial, qualitative factor list, peer comparison table"
  6. AI Explainer — "AI explanation: SHAP feature-importance horizontal bar chart, natural-language summary card, top drivers list"
  7. Monte Carlo — "Monte Carlo simulation: fan/cone projection chart, percentile stat cards (P5/P50/P95), VaR + drawdown table"
  8. Drift — "model drift: drift-score-over-time line chart, feature drift table with status badges, alert banner"
  9. 52 Features — "feature catalog: searchable 52-row feature table grouped by category, value + importance columns"
  10. FII/DII — "FII/DII flows: net flow bar chart by day, buy/sell summary stat cards, institutional table"
  11. India Signals — "India NSE signals: BUY signal cards with score gauges, capital allocation table in ₹, GTT levels"
  12. Watchlist — "halal watchlist: large ticker table, tier chips, price + score + signal columns, compact hairline rows"
  13. Zakat — "Zakat calculator: input fields card, computed zakat-due figure (large mono number), holdings breakdown table"

- [ ] **Step 2: Capture each** — for every generated screen call `get_screen` and Write its HTML to `stitch-screens/NN-<tab>.html`. If a generate call times out, wait and `get_screen` per the constraint — do not re-generate.

- [ ] **Step 3: Commit**

```bash
cd "../V-1.0" && git add stitch-screens && git commit stitch-screens -m "feat(ui): capture 13 Boro Portfolio reference screens from Stitch"
```

---

## Task 3: Boro Portfolio shell — token layer + sidebar

**Files:**
- Modify: `V-1.0/demo-boro.html` (`<head>` fonts, the `:root`/theme `<style>` block ~lines 12–50, the top `.tab-nav` markup, body layout wrapper)

**Interfaces:**
- Consumes: existing tab content `<div>`s and their JS/canvas IDs (unchanged).
- Produces: CSS custom properties + component classes (`.card`, `.stat`, `.b-table`, `.badge`, `.chart-frame`, `.sidebar`, `.tab`/`.tab.active`) every later task reuses.

- [ ] **Step 1: Replace font links** in `<head>` (drop the Inter-only link):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet"/>
```

- [ ] **Step 2: Replace the theme `<style>` `:root` block** with the Boro Portfolio token layer:

```css
:root{
  /* surfaces */
  --bg:#f7f9fd; --surface:#ffffff; --surface-low:#f2f4f7; --surface-mid:#eceef1; --surface-high:#e6e8eb;
  /* text */
  --text:#191c1e; --text-muted:#41484d; --text-faint:#71787d;
  /* brand */
  --primary:#487d9a; --primary-strong:#2d6480; --on-primary:#ffffff; --primary-soft:#d1e5f3;
  /* lines */
  --border:#c0c7cd; --border-strong:#71787d;
  /* status */
  --up:#1a7f37; --down:#ba1a1a; --warn:#b3801f; --down-soft:#ffdad6;
  /* shape + space */
  --r-sm:2px; --r:4px; --r-lg:8px; --r-xl:12px; --r-full:9999px;
  --s1:4px; --s2:8px; --s3:16px; --s4:24px; --s5:32px;
  --font-ui:'Geist',-apple-system,system-ui,sans-serif;
  --font-data:'JetBrains Mono',ui-monospace,monospace;
  --sidebar-w:240px;
}
body{background:var(--bg);color:var(--text);font-family:var(--font-ui);}
/* numbers/tickers/figures */
.mono,.stat-value,.b-table td.num{font-family:var(--font-data);font-variant-numeric:tabular-nums;}
.label-caps{font:700 11px/16px var(--font-ui);letter-spacing:.05em;text-transform:uppercase;color:var(--text-faint);}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:var(--s4);}
.stat-value{font:500 18px/24px var(--font-data);letter-spacing:-.02em;}
.b-table{width:100%;border-collapse:collapse;font-size:14px;}
.b-table th{ /* use .label-caps on header cells */ text-align:left;padding:var(--s2);border-bottom:1px solid var(--border);}
.b-table td{padding:var(--s2);border-bottom:1px solid var(--border);}
.b-table tr:hover td{background:var(--surface-low);}
.badge{display:inline-block;padding:2px 8px;border-radius:var(--r-lg);font:600 11px/16px var(--font-ui);}
.badge.up{background:#e3f3e8;color:var(--up);} .badge.down{background:var(--down-soft);color:var(--down);}
.badge.warn{background:#fdf2dd;color:var(--warn);}
.chart-frame{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:var(--s3);}
```

Delete the old `[data-theme]` dark/light variable blocks and the gradient/scrollbar-indigo rules.

- [ ] **Step 3: Convert layout to sidebar.** Wrap body content so a fixed 240px `.sidebar` holds the 13 tab buttons (vertical), and a `.content` region (margin-left:var(--sidebar-w)) holds the existing tab `<div>`s. Move the existing `.tab` buttons into the sidebar; keep their existing `onclick`/`data-tab` wiring intact. Sidebar item style:

```css
.sidebar{position:fixed;top:0;left:0;width:var(--sidebar-w);height:100vh;background:var(--surface);border-right:1px solid var(--border);padding:var(--s3) var(--s2);overflow-y:auto;}
.content{margin-left:var(--sidebar-w);padding:var(--s5);}
.tab{display:flex;gap:8px;width:100%;padding:8px 12px;border-radius:var(--r);background:transparent;border:0;color:var(--text-muted);font:500 14px/20px var(--font-ui);cursor:pointer;text-align:left;}
.tab:hover{background:var(--surface-low);}
.tab.active{background:var(--primary-soft);color:var(--primary-strong);font-weight:600;}
@media(max-width:768px){.sidebar{position:static;width:auto;height:auto;display:flex;flex-wrap:wrap;}.content{margin-left:0;}}
```

- [ ] **Step 4: Verify.** Playwright `browser_navigate` to the file, `browser_snapshot` + screenshot. Expected: light Boro canvas, left sidebar with all 13 tabs, clicking a tab still switches content, charts still draw (colors not yet themed). Confirm no console errors via `browser_console_messages`.

- [ ] **Step 5: Commit**

```bash
cd "../V-1.0" && git commit demo-boro.html -m "feat(ui): Boro Portfolio token layer + 240px sidebar shell"
```

---

## Tasks 4–16: Port each tab (one task per tab)

Repeat the **same procedure** for each tab below, in order. Each is its own task, commit, and verification gate. The procedure is identical; only the source reference file and the canvas/data IDs differ.

**Port procedure (applies to every tab task):**

**Files:** Modify `V-1.0/demo-boro.html` (only the target tab's content `<div>`). Reference: `stitch-screens/NN-<tab>.html`.

- [ ] **Step 1:** Read the existing tab `<div>` in `demo-boro.html`; note every `id`, `<canvas>` id, and DOM node the JS reads/writes (grep the `<script>` for those ids).
- [ ] **Step 2:** Read the matching `stitch-screens/NN-<tab>.html`; extract its Boro structural markup (cards, stat blocks, tables, chart container) — strip Stitch's inline `<head>`/font/script noise, keep semantic structure + Tailwind/utility classes that map to our token classes (`.card`, `.b-table`, `.label-caps`, `.badge`, `.stat-value`, `.chart-frame`).
- [ ] **Step 3:** Replace the tab's inner markup with the Boro structure. Re-insert the **original** canvas elements (same `id`) inside the new `.chart-frame`s, and keep every element id the JS depends on (rename Stitch placeholders to the real ids). Put numeric/ticker cells in `.mono`/`td.num` and table headers in `.label-caps`.
- [ ] **Step 4:** Theme this tab's Chart.js config to Boro: line stroke 1.5px, main series `#487d9a`, gridlines `#e6e8eb`, font Geist, tick/number font JetBrains Mono, up `#1a7f37` / down `#ba1a1a`. (If the tab has no chart, skip.)
- [ ] **Step 5: Verify.** Playwright: navigate, click this tab, `browser_take_screenshot`, `browser_console_messages`. Expected: tab matches Boro Portfolio look; every chart draws; every table/stat shows real data (not empty); no console errors.
- [ ] **Step 6: Commit** — `cd "../V-1.0" && git commit demo-boro.html -m "feat(ui): port <Tab> tab to Boro Portfolio"`

Tab → reference file → key dynamic hooks to preserve:

- **Task 4 — Sentiment** → `01-sentiment.html` → sentiment line canvas, headline list container, score element.
- **Task 5 — Technical** → `02-technical.html` → price chart canvas, RSI/MACD canvases or values, signal table body.
- **Task 6 — Macro** → `03-macro.html` → VIX/indicator canvas, FRED stat elements, correlation strip.
- **Task 7 — Screener** → `04-screener.html` → results table body, filter inputs.
- **Task 8 — Moat** → `05-moat.html` → moat score element/canvas, factor list, peer table body.
- **Task 9 — AI Explainer** → `06-ai-explainer.html` → SHAP bar canvas, summary text element, drivers list.
- **Task 10 — Monte Carlo** → `07-monte-carlo.html` → fan-chart canvas, percentile stat elements, VaR table body.
- **Task 11 — Drift** → `08-drift.html` → drift line canvas, drift table body, alert banner element.
- **Task 12 — 52 Features** → `09-52-features.html` → features table body (52 rows).
- **Task 13 — FII/DII** → `10-fii-dii.html` → flow bar canvas, summary stat elements, table body.
- **Task 14 — India Signals** → `11-india-signals.html` → signal cards container, allocation table body (₹).
- **Task 15 — Watchlist** → `12-watchlist.html` → watchlist table body, tier chips.
- **Task 16 — Zakat** → `13-zakat.html` → input fields, computed zakat-due element, holdings table body.

---

## Task 17: Global chart theming + cleanup + final pass

**Files:** Modify `V-1.0/demo-boro.html` (top of `<script>`: Chart.js defaults; `<style>`: remove dead rules).

- [ ] **Step 1:** Set Chart.js global defaults once so any un-themed chart inherits Boro:

```js
Chart.defaults.font.family = "Geist, system-ui, sans-serif";
Chart.defaults.color = "#41484d";
Chart.defaults.borderColor = "#e6e8eb";
Chart.defaults.elements.line.borderWidth = 1.5;
```

- [ ] **Step 2:** Delete any remaining dark-theme CSS, the theme-toggle button + its JS handler, and unused indigo/gradient rules.
- [ ] **Step 3: Full sweep verification.** Playwright: navigate, then for EACH of the 13 tabs — click it, screenshot, check `browser_console_messages`. Expected: all 13 match Boro Portfolio; every chart/table populated; zero console errors; sidebar collapses correctly at 768px (`browser_resize` to 600px wide and confirm).
- [ ] **Step 4: Commit** — `cd "../V-1.0" && git commit demo-boro.html -m "feat(ui): global Chart.js Boro theming + remove dead dark-theme code"`

---

## Done / handoff

After Task 17, present the finished `demo-boro.html` for review and offer the swap: replace `demo.html` with `demo-boro.html` (separate commit) only on user approval. Update `CLAUDE.md`'s "static 13-tab dashboard" note if the filename changes.
