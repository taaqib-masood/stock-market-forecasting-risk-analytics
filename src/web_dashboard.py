"""
Enhanced Web Dashboard v2 — localhost:5000
==========================================
New in v2:
  - Market regime panel with confidence gauge
  - Equity curve chart (Chart.js)
  - Sector strength heatmap
  - Correlation risk panel
  - Signal quality breakdown (backtest stats, gap risk, MTF)
  - Volatility-adjusted sizing shown per trade
  - Dynamic stop type indicator
  - Mobile-first responsive layout

Run: python -m src.web_dashboard --capital 50000
"""

import json, os, threading, argparse, contextlib, io
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

PORT    = int(os.environ.get("WEB_PORT", 5000))
CAPITAL = float(os.environ.get("WEBHOOK_CAPITAL", 50_000))

# ── API ───────────────────────────────────────────────────────────────────────

def _portfolio():
    from src.paper_trader import _load, portfolio_value, trade_stats
    s = _load()
    return {"portfolio": portfolio_value(s), "stats": trade_stats(s),
            "trades": s["trades"][-30:]}

def _signals():
    from src.scanner import scan
    from src.earnings_guard import filter_cards as eg_filter
    from src.gap_risk import filter_cards as gap_filter
    from src.regime_detector import detect
    r = detect()
    cards = scan(capital=CAPITAL, top_n=5)
    safe, blocked_earn = eg_filter(cards, days=5)
    safe, blocked_gap  = gap_filter(safe, vix=r.vix)
    return {
        "signals":     safe[:3],
        "blocked":     blocked_earn + blocked_gap,
        "scanned_at":  datetime.now().strftime("%H:%M:%S"),
        "regime":      r.name,
        "regime_conf": r.confidence,
        "min_score":   r.min_score,
    }

def _regime():
    from src.regime_detector import detect, regime_emoji
    r = detect()
    return {
        "name": r.name, "confidence": r.confidence,
        "emoji": regime_emoji(r.name), "vix": r.vix,
        "nifty": r.nifty_price, "ret1w": r.nifty_ret1w,
        "ret1m": r.nifty_ret1m, "description": r.description,
        "max_positions": r.max_positions,
        "position_size_mul": r.position_size_mul,
        "use_trailing_stop": r.use_trailing_stop,
    }

def _sectors():
    from src.sector_rotation import rank_sectors, _sector_score, SECTORS
    scores = {name: _sector_score(tickers) for name, tickers in SECTORS.items()}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return {"sectors": [{"name": n, "score": s} for n, s in ranked]}

def _correlation():
    from src.paper_trader import _load
    from src.correlation import portfolio_correlation_risk
    state = _load()
    tickers = list(state["positions"].keys())
    if len(tickers) < 2:
        return {"avg_corr": 0, "max_corr": 0, "pairs": [], "matrix": {}}
    return portfolio_correlation_risk(tickers)

def _log_trade(ticker, shares, price):
    from src.paper_trader import _load, buy
    s = _load(); return buy(ticker.upper(), int(shares), float(price), state=s)

def _close_trade(ticker, price):
    from src.paper_trader import _load, sell
    s = _load(); return sell(ticker.upper(), price=float(price), state=s)

# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NSE Trade Intelligence</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--surface:#161b22;--border:#30363d;--card:#1c2128;
  --green:#3fb950;--red:#f85149;--yellow:#d29922;--blue:#58a6ff;
  --cyan:#39d353;--purple:#bc8cff;--text:#e6edf3;--muted:#8b949e;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;}
.header{background:var(--surface);border-bottom:1px solid var(--border);
  padding:14px 20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;}
.header h1{font-size:17px;color:var(--blue);white-space:nowrap;}
.header-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.tabs{display:flex;gap:0;background:var(--surface);border-bottom:1px solid var(--border);overflow-x:auto;}
.tab{padding:10px 18px;cursor:pointer;color:var(--muted);border-bottom:2px solid transparent;
  white-space:nowrap;font-size:13px;transition:all .2s;}
.tab.active{color:var(--blue);border-bottom-color:var(--blue);}
.tab:hover{color:var(--text);}
.page{display:none;padding:16px 20px;}.page.active{display:block;}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;}
.card h3{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px;}
.stat-val{font-size:22px;font-weight:700;margin-bottom:2px;}
.stat-sub{font-size:12px;color:var(--muted);}
.green{color:var(--green);}.red{color:var(--red);}.yellow{color:var(--yellow);}
.blue{color:var(--blue);}.purple{color:var(--purple);}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;}
.b-green{background:rgba(63,185,80,.15);color:var(--green);}
.b-red{background:rgba(248,81,73,.15);color:var(--red);}
.b-yellow{background:rgba(210,153,34,.15);color:var(--yellow);}
.b-blue{background:rgba(88,166,255,.15);color:var(--blue);}
.b-purple{background:rgba(188,140,255,.15);color:var(--purple);}
table{width:100%;border-collapse:collapse;}
th{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;
   letter-spacing:.8px;padding:8px 10px;border-bottom:1px solid var(--border);}
td{padding:9px 10px;border-bottom:1px solid var(--border);font-size:13px;}
tr:hover td{background:var(--surface);}
.btn{background:var(--blue);color:#000;border:none;border-radius:6px;
     padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;}
.btn:hover{opacity:.85;}.btn-red{background:var(--red);color:#fff;}
.btn-ghost{background:none;border:1px solid var(--border);color:var(--muted);
           border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;}
.btn-ghost:hover{border-color:var(--blue);color:var(--blue);}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);
       z-index:100;align-items:center;justify-content:center;}
.modal.open{display:flex;}
.modal-box{background:var(--surface);border:1px solid var(--border);
           border-radius:10px;padding:22px;min-width:300px;max-width:420px;width:90%;}
.modal-box h3{margin-bottom:14px;font-size:15px;}
input{background:var(--bg);border:1px solid var(--border);color:var(--text);
      border-radius:6px;padding:8px 12px;width:100%;margin-bottom:10px;font-size:14px;}
.actions{display:flex;gap:8px;margin-top:6px;}
.progress-bar{background:var(--border);border-radius:4px;height:8px;overflow:hidden;margin-top:6px;}
.progress-fill{height:100%;border-radius:4px;transition:width .5s;}
.regime-box{border-radius:8px;padding:14px;border:1px solid;margin-bottom:16px;}
.signal-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;}
.signal-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;}
.signal-row{display:flex;justify-content:space-between;padding:4px 0;
            border-bottom:1px solid var(--border);font-size:13px;}
.signal-row:last-of-type{border:none;}
.tag{background:var(--border);border-radius:4px;padding:1px 6px;font-size:11px;margin:1px;display:inline-block;}
.tag-ok{background:rgba(63,185,80,.2);color:var(--green);}
.tag-warn{background:rgba(210,153,34,.2);color:var(--yellow);}
.tag-block{background:rgba(248,81,73,.2);color:var(--red);}
.sector-bar{height:28px;border-radius:4px;display:flex;align-items:center;
            padding:0 10px;font-size:12px;font-weight:600;margin-bottom:6px;
            transition:width .6s;background:var(--border);position:relative;}
.sector-fill{position:absolute;left:0;top:0;bottom:0;border-radius:4px;transition:width .6s;}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);
         border-top-color:var(--blue);border-radius:50%;animation:spin .8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.empty{color:var(--muted);text-align:center;padding:28px;font-size:13px;}
.corr-cell{padding:6px 8px;text-align:center;font-size:11px;border-radius:3px;}
.section-title{font-size:13px;color:var(--muted);text-transform:uppercase;
               letter-spacing:.8px;margin:16px 0 10px;border-bottom:1px solid var(--border);padding-bottom:6px;}
@media(max-width:700px){
  .grid-4{grid-template-columns:1fr 1fr;}
  .grid-3{grid-template-columns:1fr;}
  .page{padding:10px 12px;}
}
</style>
</head>
<body>

<div class="header">
  <div><h1>📈 NSE Trade Intelligence</h1></div>
  <div class="header-right">
    <span id="regime-badge" class="badge b-yellow">Loading...</span>
    <span id="hdr-nifty" style="color:var(--muted);font-size:12px"></span>
    <button class="btn-ghost" onclick="loadAll()">↻ Refresh</button>
    <button class="btn" onclick="openModal('log-modal')">+ Log Trade</button>
    <button class="btn btn-red" onclick="openModal('close-modal')">✕ Close Position</button>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('signals')">Signals</div>
  <div class="tab" onclick="showTab('portfolio')">Portfolio</div>
  <div class="tab" onclick="showTab('analytics')">Analytics</div>
  <div class="tab" onclick="showTab('regime')">Market Regime</div>
</div>

<!-- OVERVIEW TAB -->
<div id="tab-overview" class="page active">
  <div class="grid-4">
    <div class="card"><h3>Portfolio Value</h3>
      <div class="stat-val" id="ov-total">—</div>
      <div class="stat-sub" id="ov-pnl">—</div></div>
    <div class="card"><h3>Cash Available</h3>
      <div class="stat-val" id="ov-cash">—</div>
      <div class="stat-sub" id="ov-pos-val">—</div></div>
    <div class="card"><h3>Win Rate</h3>
      <div class="stat-val" id="ov-wr">—</div>
      <div class="stat-sub" id="ov-trades">— trades</div></div>
    <div class="card"><h3>Profit Factor</h3>
      <div class="stat-val" id="ov-pf">—</div>
      <div class="stat-sub" id="ov-pnl-rs">—</div></div>
  </div>
  <div class="grid-2">
    <div class="card" style="height:260px">
      <h3>Equity Curve</h3>
      <canvas id="equity-chart"></canvas>
    </div>
    <div class="card">
      <h3>Sector Strength</h3>
      <div id="sector-bars"><div class="empty">Loading...</div></div>
    </div>
  </div>
  <div class="card" style="margin-top:12px">
    <h3>Today's Top Signals <span id="ov-scan-time" style="font-weight:400;font-size:11px"></span></h3>
    <div id="ov-signals"><div class="empty">Loading...</div></div>
  </div>
</div>

<!-- SIGNALS TAB -->
<div id="tab-signals" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <div>
      <span id="sig-regime-note" style="color:var(--muted);font-size:13px"></span>
    </div>
    <button class="btn-ghost" onclick="loadSignals()">
      <span id="sig-spinner" style="display:none" class="spinner"></span> Rescan NSE
    </button>
  </div>
  <div id="signals-container" class="signal-grid">
    <div class="empty">Click "Rescan NSE" to find today's setups.</div>
  </div>
  <div id="blocked-container" style="margin-top:16px"></div>
</div>

<!-- PORTFOLIO TAB -->
<div id="tab-portfolio" class="page">
  <div class="section-title">Open Positions</div>
  <div id="pos-table"><div class="empty">No open positions</div></div>
  <div class="section-title" style="margin-top:20px">Closed Trades</div>
  <table>
    <thead><tr><th>Ticker</th><th>Shares</th><th>Entry</th><th>Exit</th>
      <th>P&L</th><th>%</th><th>Result</th><th>Date</th></tr></thead>
    <tbody id="history-body"><tr><td colspan="8" class="empty">No closed trades</td></tr></tbody>
  </table>
  <div id="corr-section" style="margin-top:20px"></div>
</div>

<!-- ANALYTICS TAB -->
<div id="tab-analytics" class="page">
  <div class="grid-3">
    <div class="card"><h3>Win Rate</h3><div class="stat-val" id="an-wr">—</div>
      <div class="progress-bar"><div class="progress-fill green" id="an-wr-bar" style="width:0%"></div></div>
      <div class="stat-sub" style="margin-top:6px" id="an-trades">—</div></div>
    <div class="card"><h3>Profit Factor</h3><div class="stat-val" id="an-pf">—</div>
      <div class="stat-sub" id="an-pf-note">Gross profit / gross loss</div></div>
    <div class="card"><h3>Total P&L</h3><div class="stat-val" id="an-pnl">—</div>
      <div class="stat-sub" id="an-avg">avg per trade</div></div>
    <div class="card"><h3>Avg Win</h3><div class="stat-val green" id="an-win">—</div>
      <div class="stat-sub" id="an-win-n">— winning trades</div></div>
    <div class="card"><h3>Avg Loss</h3><div class="stat-val red" id="an-loss">—</div>
      <div class="stat-sub" id="an-loss-n">— losing trades</div></div>
    <div class="card"><h3>Win:Loss Ratio</h3><div class="stat-val" id="an-wlr">—</div>
      <div class="stat-sub">avg win / avg loss</div></div>
  </div>
  <div class="card" style="margin-top:12px;height:300px">
    <h3>Monthly P&L</h3>
    <canvas id="monthly-chart"></canvas>
  </div>
  <div class="card" style="margin-top:12px">
    <h3>Recent Trades</h3>
    <table>
      <thead><tr><th>Ticker</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Result</th><th>Date</th></tr></thead>
      <tbody id="an-history"></tbody>
    </table>
  </div>
</div>

<!-- REGIME TAB -->
<div id="tab-regime" class="page">
  <div id="regime-detail"><div class="empty">Loading regime data...</div></div>
</div>

<!-- MODALS -->
<div class="modal" id="log-modal">
  <div class="modal-box"><h3>Log Paper Trade</h3>
    <input id="lt-ticker" placeholder="Ticker (e.g. RELIANCE)"/>
    <input id="lt-shares" placeholder="Shares" type="number"/>
    <input id="lt-price"  placeholder="Entry price" type="number" step="0.01"/>
    <input id="lt-stop"   placeholder="Stop loss price (optional)" type="number" step="0.01"/>
    <input id="lt-target" placeholder="Target price (optional)" type="number" step="0.01"/>
    <div class="actions">
      <button class="btn" onclick="submitLog()">Log Trade</button>
      <button class="btn-ghost" onclick="closeModal('log-modal')">Cancel</button>
    </div>
    <div id="lt-result" style="margin-top:10px;font-size:12px"></div>
  </div>
</div>
<div class="modal" id="close-modal">
  <div class="modal-box"><h3>Close Position</h3>
    <input id="ct-ticker" placeholder="Ticker"/>
    <input id="ct-price"  placeholder="Exit price" type="number" step="0.01"/>
    <div class="actions">
      <button class="btn btn-red" onclick="submitClose()">Close Trade</button>
      <button class="btn-ghost" onclick="closeModal('close-modal')">Cancel</button>
    </div>
    <div id="ct-result" style="margin-top:10px;font-size:12px"></div>
  </div>
</div>

<script>
// ── Helpers ───────────────────────────────────────────────────────────────────
const rs  = n => '₹' + parseFloat(n).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct = n => (n>=0?'+':'')+parseFloat(n).toFixed(2)+'%';
const col = n => parseFloat(n)>=0?'green':'red';
const el  = id => document.getElementById(id);

let equityChart = null, monthlyChart = null;

// ── Tab switching ─────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i)=>{
    const names=['overview','signals','portfolio','analytics','regime'];
    t.classList.toggle('active', names[i]===name);
  });
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  el('tab-'+name).classList.add('active');
  if(name==='signals'&&!el('signals-container').dataset.loaded) loadSignals();
  if(name==='analytics') renderAnalytics();
  if(name==='regime') loadRegime();
  if(name==='portfolio') loadCorrelation();
}

function openModal(id){el(id).classList.add('open');}
function closeModal(id){el(id).classList.remove('open');
  el(id).querySelectorAll('input').forEach(i=>i.value='');
  ['lt-result','ct-result'].forEach(x=>{if(el(x))el(x).textContent='';});}

// ── Portfolio ─────────────────────────────────────────────────────────────────
async function loadPortfolio() {
  const r = await fetch('/api/portfolio'), d = await r.json();
  const p = d.portfolio, s = d.stats;

  el('ov-total').textContent = rs(p.total_val);
  el('ov-total').className   = 'stat-val '+col(p.total_pnl);
  el('ov-pnl').textContent   = pct(p.total_pnl_pct)+' total  ('+rs(p.total_pnl)+')';
  el('ov-cash').textContent  = rs(p.cash);
  el('ov-pos-val').textContent = 'Positions: '+rs(p.positions_val);
  el('ov-wr').textContent    = s.win_rate?s.win_rate+'%':'—';
  el('ov-wr').className      = 'stat-val '+(s.win_rate>=55?'green':s.win_rate>=45?'yellow':'red');
  el('ov-trades').textContent = (s.total||0)+' closed trades';
  el('ov-pf').textContent    = s.profit_factor||'—';
  el('ov-pf').className      = 'stat-val '+(s.profit_factor>=1.5?'green':'yellow');
  el('ov-pnl-rs').textContent = 'Total: '+(s.total_pnl?rs(s.total_pnl):'₹0.00');

  // Equity chart
  if(d.trades && d.trades.length>0){
    let eq=50000, eqData=[{x:0,y:eq}];
    d.trades.forEach((t,i)=>{eq+=t.pnl;eqData.push({x:i+1,y:Math.round(eq)});});
    renderEquityChart(eqData);
  }

  // Open positions table
  const posDiv = el('pos-table');
  if(!p.marked||Object.keys(p.marked).length===0){
    posDiv.innerHTML='<div class="empty">No open positions.</div>';
  }else{
    let h='<table><thead><tr><th>Ticker</th><th>Shares</th><th>Avg Entry</th><th>Current</th><th>Value</th><th>Unrealised</th><th>Stop</th><th>Target</th></tr></thead><tbody>';
    for(const[t,m] of Object.entries(p.marked)){
      const uc=m.unrealised>=0?'green':'red';
      h+=`<tr><td><b>${t}</b></td><td>${m.shares}</td><td>${rs(m.avg_entry)}</td>
          <td>${rs(m.current_price)}</td><td>${rs(m.market_value)}</td>
          <td class="${uc}">${rs(m.unrealised)} (${pct(m.unrealised_pct)})</td>
          <td class="red">${m.stop?rs(m.stop):'—'}</td>
          <td class="green">${m.target?rs(m.target):'—'}</td></tr>`;
    }
    posDiv.innerHTML=h+'</tbody></table>';
  }

  // History
  const tb=el('history-body');
  if(!d.trades||!d.trades.length){
    tb.innerHTML='<tr><td colspan="8" class="empty">No closed trades</td></tr>';
  }else{
    tb.innerHTML=[...d.trades].reverse().map(t=>{
      const pc=t.pnl>0?'green':'red';
      return `<tr><td><b>${t.ticker}</b></td><td>${t.shares}</td>
              <td>${rs(t.entry)}</td><td>${rs(t.exit)}</td>
              <td class="${pc}">${rs(t.pnl)}</td>
              <td class="${pc}">${pct(t.pnl_pct)}</td>
              <td><span class="badge ${t.outcome==='WIN'?'b-green':'b-red'}">${t.outcome}</span></td>
              <td>${(t.closed_at||'').slice(0,10)}</td></tr>`;
    }).join('');
  }
  window._portfolioData = d;
}

function renderAnalytics() {
  const d = window._portfolioData;
  if(!d||!d.stats) return;
  const s=d.stats;
  el('an-wr').textContent   = s.win_rate?s.win_rate+'%':'—';
  el('an-wr').className     = 'stat-val '+(s.win_rate>=55?'green':s.win_rate>=45?'yellow':'red');
  el('an-wr-bar').style.width = (s.win_rate||0)+'%';
  el('an-pf').textContent   = s.profit_factor||'—';
  el('an-pf').className     = 'stat-val '+(s.profit_factor>=1.5?'green':'yellow');
  el('an-pnl').textContent  = s.total_pnl?rs(s.total_pnl):'—';
  el('an-pnl').className    = 'stat-val '+col(s.total_pnl||0);
  el('an-trades').textContent= (s.total||0)+' closed  ('+( s.wins||0)+' wins / '+(s.losses||0)+' losses)';
  el('an-win').textContent  = s.avg_win?rs(s.avg_win):'—';
  el('an-loss').textContent = s.avg_loss?rs(s.avg_loss):'—';
  el('an-win-n').textContent= (s.wins||0)+' winning trades';
  el('an-loss-n').textContent=(s.losses||0)+' losing trades';
  const wlr = s.avg_win&&s.avg_loss ? (Math.abs(s.avg_win)/Math.abs(s.avg_loss)).toFixed(2) : '—';
  el('an-wlr').textContent  = wlr;
  el('an-wlr').className    = 'stat-val '+(parseFloat(wlr)>=1.5?'green':'yellow');
  el('an-avg').textContent  = s.total_pnl&&s.total ? 'avg '+rs(s.total_pnl/s.total)+'/trade' : '—';

  if(d.trades&&d.trades.length){
    el('an-history').innerHTML=[...d.trades].reverse().slice(0,10).map(t=>{
      const pc=t.pnl>0?'green':'red';
      return `<tr><td><b>${t.ticker}</b></td><td>${rs(t.entry)}</td><td>${rs(t.exit)}</td>
              <td class="${pc}">${rs(t.pnl)}</td>
              <td><span class="badge ${t.outcome==='WIN'?'b-green':'b-red'}">${t.outcome}</span></td>
              <td>${(t.closed_at||'').slice(0,10)}</td></tr>`;
    }).join('');
    renderMonthlyChart(d.trades);
  }
}

// ── Signals ───────────────────────────────────────────────────────────────────
async function loadSignals(){
  el('sig-spinner').style.display='inline-block';
  el('signals-container').innerHTML='<div class="empty"><span class="spinner"></span> Scanning NSE (~30s)...</div>';
  const r=await fetch('/api/signals'), d=await r.json();
  el('sig-spinner').style.display='none';
  el('signals-container').dataset.loaded='1';
  el('ov-scan-time').textContent='scanned '+d.scanned_at;
  el('sig-regime-note').textContent=
    `Regime: ${d.regime}  |  Min score required: ${d.min_score}  |  Scanned at ${d.scanned_at}`;

  const sc=el('signals-container');
  if(!d.signals||!d.signals.length){
    sc.innerHTML=`<div class="empty">
      <b>No high-conviction signals right now.</b><br><br>
      Regime: <b>${d.regime}</b>  |  Min score: ${d.min_score}<br><br>
      ${d.regime==='TRENDING_DOWN'||d.regime==='CRASH'
        ?'⚠️ Market is in downtrend. Cash is the safest position.'
        :'Indicators are mixed. Check again tomorrow at 9 AM.'}
    </div>`;
    el('ov-signals').innerHTML=sc.innerHTML;
  }else{
    sc.innerHTML=d.signals.map((c,i)=>signalCard(c,i)).join('');
    el('ov-signals').innerHTML=d.signals.slice(0,2).map((c,i)=>signalCardCompact(c,i)).join('');
  }

  if(d.blocked&&d.blocked.length){
    el('blocked-container').innerHTML=`
      <div class="section-title">Blocked Signals (${d.blocked.length})</div>
      ${d.blocked.map(c=>`<div class="card" style="margin-bottom:8px;opacity:.7">
        <span class="badge b-red">BLOCKED</span> <b>${c.ticker}</b> —
        ${c.blocked_reason||c.gap_block_reason||'filtered'}
      </div>`).join('')}`;
  }
}

function signalCard(c,i){
  const sp=((c.stop/c.entry-1)*100).toFixed(1);
  const tp=((c.target/c.entry-1)*100).toFixed(1);
  const mtf=c.mtf_confirmed?'<span class="tag tag-ok">✓ Weekly</span>':'<span class="tag tag-warn">⚠ Weekly</span>';
  const bt=c.backtest?`<span class="tag tag-ok">✓ BT ${c.backtest.win_rate}%</span>`:'';
  const gr=c.gap_risk?`<span class="tag ${c.gap_risk.verdict==='LOW'?'tag-ok':'tag-warn'}">Gap: ${c.gap_risk.verdict}</span>`:'';
  const sc_color=c.score>=75?'var(--green)':c.score>=60?'var(--yellow)':'var(--red)';
  return `<div class="signal-card">
    <div style="display:flex;justify-content:space-between;margin-bottom:8px">
      <span style="font-size:17px;font-weight:700;color:var(--blue)">#${i+1} ${c.ticker}</span>
      <span class="badge b-green">${c.signal}</span>
    </div>
    <div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted)">
        <span>Score</span><span style="color:${sc_color}">${c.score}/100</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${c.score}%;background:${sc_color}"></div></div>
    </div>
    <div style="margin-bottom:8px">${mtf}${bt}${gr}</div>
    <div class="signal-row"><span style="color:var(--muted)">Entry</span><b>${rs(c.entry)}</b></div>
    <div class="signal-row"><span style="color:var(--muted)">Stop</span><span class="red">${rs(c.stop)} (${sp}%)</span></div>
    <div class="signal-row"><span style="color:var(--muted)">Target</span><span class="green">${rs(c.target)} (+${tp}%)</span></div>
    <div class="signal-row"><span style="color:var(--muted)">R:R</span><span class="green">${c.rr} : 1</span></div>
    <div class="signal-row"><span style="color:var(--muted)">Shares</span>${c.shares}
      <span style="color:var(--muted)">Invest</span>${rs(c.invest)}</div>
    <div class="signal-row"><span style="color:var(--muted)">Risk</span><span class="red">${rs(c.risk_rs)}</span>
      <span style="color:var(--muted)">Reward</span><span class="green">${rs(c.reward_rs)}</span></div>
    <div class="signal-row"><span style="color:var(--muted)">RSI</span>${c.rsi}
      <span style="color:var(--muted)">Vol</span>${c.vol_surge}x</div>
    <button class="btn" style="width:100%;margin-top:10px;font-size:12px"
      onclick="prefillLog('${c.ticker}',${c.shares},${c.entry})">Log this trade</button>
  </div>`;
}

function signalCardCompact(c,i){
  const sp=((c.stop/c.entry-1)*100).toFixed(1);
  const tp=((c.target/c.entry-1)*100).toFixed(1);
  return `<div style="display:flex;justify-content:space-between;align-items:center;
    padding:10px;border:1px solid var(--border);border-radius:6px;margin-bottom:8px">
    <div><b>${c.ticker}</b> <span class="badge b-green">BUY</span>
      <span style="margin-left:8px;font-size:12px;color:var(--muted)">${c.score}/100</span></div>
    <div style="text-align:right;font-size:12px">
      <span style="color:var(--green)">+${tp}%</span> target &nbsp;
      <span style="color:var(--red)">${sp}%</span> stop &nbsp;
      <span style="color:var(--blue)">${c.rr}:1</span>
    </div>
  </div>`;
}

// ── Sectors ───────────────────────────────────────────────────────────────────
async function loadSectors(){
  const r=await fetch('/api/sectors'), d=await r.json();
  const max=d.sectors[0]?.score||100;
  const colors=['#3fb950','#58a6ff','#d29922','#bc8cff','#39d353','#f85149','#79c0ff','#ffa657'];
  el('sector-bars').innerHTML=d.sectors.map((s,i)=>{
    const w=Math.max(5,(s.score/100*100));
    const col=s.score>=60?colors[0]:s.score>=40?colors[1]:s.score>=20?colors[2]:colors[5];
    return `<div style="margin-bottom:5px">
      <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:2px">
        <span>${s.name}</span><span>${s.score}/100</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" style="width:${w}%;background:${col}"></div>
      </div>
    </div>`;
  }).join('');
}

// ── Regime ────────────────────────────────────────────────────────────────────
async function loadRegime(){
  const r=await fetch('/api/regime'), d=await r.json();
  const colors={TRENDING_UP:'var(--green)',TRENDING_DOWN:'var(--red)',
    RANGING:'var(--yellow)',BREAKOUT:'var(--blue)',CRASH:'var(--red)'};
  const c=colors[d.name]||'var(--yellow)';

  el('regime-badge').textContent=d.emoji+' '+d.name;
  el('hdr-nifty').textContent='Nifty '+rs(d.nifty)+' ('+pct(d.ret1w)+' 1W)';

  el('regime-detail').innerHTML=`
    <div class="regime-box" style="border-color:${c};background:${c}18">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div><span style="font-size:24px">${d.emoji}</span>
          <span style="font-size:20px;font-weight:700;color:${c};margin-left:10px">${d.name}</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:24px;font-weight:700;color:${c}">${d.confidence}%</div>
          <div style="font-size:11px;color:var(--muted)">confidence</div>
        </div>
      </div>
      <div style="margin-top:10px;color:var(--muted);font-size:13px">${d.description}</div>
    </div>
    <div class="grid-3" style="margin-top:12px">
      <div class="card"><h3>VIX (Fear Index)</h3>
        <div class="stat-val ${d.vix>=25?'red':d.vix>=15?'yellow':'green'}">${d.vix}</div>
        <div class="stat-sub">${d.vix>=30?'⚠ Panic zone':d.vix>=20?'Elevated':'Normal'}</div></div>
      <div class="card"><h3>Nifty 1-Week</h3>
        <div class="stat-val ${col(d.ret1w)}">${pct(d.ret1w)}</div>
        <div class="stat-sub">vs last week</div></div>
      <div class="card"><h3>Nifty 1-Month</h3>
        <div class="stat-val ${col(d.ret1m)}">${pct(d.ret1m)}</div>
        <div class="stat-sub">vs last month</div></div>
    </div>
    <div class="grid-3" style="margin-top:12px">
      <div class="card"><h3>Max Positions</h3>
        <div class="stat-val ${d.max_positions===0?'red':'green'}">${d.max_positions}</div>
        <div class="stat-sub">allowed in this regime</div></div>
      <div class="card"><h3>Position Size</h3>
        <div class="stat-val ${d.position_size_mul<0.5?'red':d.position_size_mul<1?'yellow':'green'}">
          ${d.position_size_mul}x</div>
        <div class="stat-sub">of normal size</div></div>
      <div class="card"><h3>Trailing Stop</h3>
        <div class="stat-val ${d.use_trailing_stop?'green':'yellow'}">${d.use_trailing_stop?'ON':'OFF'}</div>
        <div class="stat-sub">${d.use_trailing_stop?'Chandelier trailing':'Fixed stop'}</div></div>
    </div>
    <div class="card" style="margin-top:12px">
      <h3>Strategy Guide for ${d.name}</h3>
      <table><tbody>
        ${regimeGuide(d.name).map(row=>`<tr><td style="width:35%;color:var(--muted)">${row[0]}</td><td>${row[1]}</td></tr>`).join('')}
      </tbody></table>
    </div>`;
}

function regimeGuide(name){
  const guides={
    TRENDING_UP:[['Action','Aggressively look for BUY setups'],['Stop type','Chandelier trailing — lock in profits'],['Add positions','Yes — pyramid into winners'],['Avoid','Shorting, FMCG (defensive sectors underperform)']],
    TRENDING_DOWN:[['Action','Stay in cash. No new BUY trades.'],['Stop type','Tight fixed stops on any existing trades'],['Add positions','No. Exit quickly.'],['Watch for','Reversal signal — RSI < 30 + volume spike']],
    RANGING:[['Action','Only RSI mean-reversion setups (RSI<35 or >65)'],['Stop type','Fixed 1.5×ATR — tighter in range'],['Add positions','No — take profits quickly at range edge'],['Avoid','Momentum plays — they fail in ranging markets']],
    BREAKOUT:[['Action','Watch for volume breakouts above resistance'],['Stop type','Trailing — new trend may be starting'],['Add positions','Small initial position, add on confirmation'],['Sectors','IT, Banking tend to lead breakouts']],
    CRASH:[['Action','100% cash. Do not trade.'],['Stop type','Exit all open positions'],['Add positions','Absolutely not'],['Wait for','VIX to fall below 25 + Nifty above 20-day MA']],
  };
  return guides[name]||[['Status','Regime data loading...']];
}

// ── Correlation ───────────────────────────────────────────────────────────────
async function loadCorrelation(){
  const r=await fetch('/api/correlation'), d=await r.json();
  const div=el('corr-section');
  if(!d.pairs||d.pairs.length===0){
    div.innerHTML='<div class="section-title">Portfolio Correlation</div><div class="empty" style="padding:16px">No correlation data (need 2+ positions)</div>';return;
  }
  let html=`<div class="section-title">Portfolio Correlation Risk
    <span class="badge ${d.avg_corr>0.7?'b-red':d.avg_corr>0.5?'b-yellow':'b-green'}" style="margin-left:8px">
      Avg: ${d.avg_corr}</span></div>`;
  if(d.pairs.length){
    html+=d.pairs.map(p=>{
      const c=Math.abs(p.corr);const col=c>0.75?'red':c>0.5?'yellow':'green';
      return `<div style="display:flex;justify-content:space-between;padding:8px 10px;
        border:1px solid var(--border);border-radius:6px;margin-bottom:6px">
        <span><b>${p.a}</b> ↔ <b>${p.b}</b></span>
        <span class="${col}">${p.corr>0?'+':''}${p.corr}</span>
      </div>`;
    }).join('');
  }
  div.innerHTML=html;
}

// ── Charts ────────────────────────────────────────────────────────────────────
function renderEquityChart(data){
  const ctx=el('equity-chart');
  if(!ctx)return;
  if(equityChart){equityChart.destroy();}
  equityChart=new Chart(ctx,{
    type:'line',
    data:{datasets:[{data,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,.08)',
      borderWidth:2,pointRadius:3,tension:.3,fill:true}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{display:false},y:{ticks:{color:'#8b949e',
        callback:v=>'₹'+v.toLocaleString('en-IN')},grid:{color:'#30363d'}}}}
  });
}

function renderMonthlyChart(trades){
  const ctx=el('monthly-chart');
  if(!ctx||!trades.length)return;
  const monthly={};
  trades.forEach(t=>{
    const m=(t.closed_at||'').slice(0,7);
    if(m)monthly[m]=(monthly[m]||0)+t.pnl;
  });
  const keys=Object.keys(monthly).sort();
  const vals=keys.map(k=>monthly[k]);
  if(monthlyChart)monthlyChart.destroy();
  monthlyChart=new Chart(ctx,{
    type:'bar',
    data:{labels:keys,datasets:[{data:vals,
      backgroundColor:vals.map(v=>v>=0?'rgba(63,185,80,.7)':'rgba(248,81,73,.7)'),
      borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#8b949e'},grid:{display:false}},
               y:{ticks:{color:'#8b949e',callback:v=>'₹'+v.toLocaleString('en-IN')},grid:{color:'#30363d'}}}}
  });
}

// ── Log / Close ───────────────────────────────────────────────────────────────
function prefillLog(ticker,shares,price){
  el('lt-ticker').value=ticker;el('lt-shares').value=shares;el('lt-price').value=price;
  openModal('log-modal');
}
async function submitLog(){
  const ticker=el('lt-ticker').value.trim().toUpperCase();
  const shares=parseInt(el('lt-shares').value);
  const price=parseFloat(el('lt-price').value);
  if(!ticker||!shares||!price)return;
  const r=await fetch('/api/log_trade',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ticker,shares,price})});
  const d=await r.json(),res=el('lt-result');
  if(d.ok){res.style.color='var(--green)';res.textContent='✓ Logged: '+ticker+' '+shares+' @ ₹'+price;
    setTimeout(()=>{closeModal('log-modal');loadPortfolio();},1200);}
  else{res.style.color='var(--red)';res.textContent='✗ '+d.reason;}
}
async function submitClose(){
  const ticker=el('ct-ticker').value.trim().toUpperCase();
  const price=parseFloat(el('ct-price').value);
  if(!ticker||!price)return;
  const r=await fetch('/api/close_trade',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,price})});
  const d=await r.json(),res=el('ct-result');
  if(d.ok){const pc=d.pnl>0?'var(--green)':'var(--red)';
    res.style.color=pc;res.textContent='✓ Closed '+ticker+'  P&L: ₹'+d.pnl.toFixed(2);
    setTimeout(()=>{closeModal('close-modal');loadPortfolio();},1200);}
  else{res.style.color='var(--red)';res.textContent='✗ '+d.reason;}
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function loadAll(){
  await Promise.all([loadPortfolio(),loadSectors(),loadRegime()]);
}
loadAll();
setInterval(loadPortfolio,60000);
</script>
</body>
</html>"""


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _json(self,status,data):
        b=json.dumps(data,default=str).encode()
        self.send_response(status);self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def _html(self,body):
        b=body.encode()
        self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def _body(self):
        n=int(self.headers.get("Content-Length",0))
        try: return json.loads(self.rfile.read(n))
        except: return {}
    def do_GET(self):
        p=urlparse(self.path).path
        try:
            if   p=="/": self._html(HTML)
            elif p=="/api/portfolio":  self._json(200,_portfolio())
            elif p=="/api/signals":    self._json(200,_signals())
            elif p=="/api/regime":     self._json(200,_regime())
            elif p=="/api/sectors":    self._json(200,_sectors())
            elif p=="/api/correlation":self._json(200,_correlation())
            else: self._json(404,{"error":"not found"})
        except Exception as e: self._json(500,{"error":str(e)})
    def do_POST(self):
        p=urlparse(self.path).path;b=self._body()
        try:
            if   p=="/api/log_trade":   self._json(200,_log_trade(b["ticker"],b["shares"],b["price"]))
            elif p=="/api/close_trade": self._json(200,_close_trade(b["ticker"],b["price"]))
            else: self._json(404,{"error":"not found"})
        except Exception as e: self._json(500,{"ok":False,"reason":str(e)})


def run(port=PORT,capital=CAPITAL):
    global CAPITAL; CAPITAL=capital
    import socket
    ip=socket.gethostbyname(socket.gethostname())
    server=HTTPServer(("0.0.0.0",port),Handler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║      NSE Trade Intelligence v2 — Web Dashboard      ║
╠══════════════════════════════════════════════════════╣
║  Local   : http://localhost:{port}                     ║
║  Network : http://{ip}:{port}                ║
╠══════════════════════════════════════════════════════╣
║  5 tabs: Overview · Signals · Portfolio              ║
║          Analytics · Market Regime                   ║
╚══════════════════════════════════════════════════════╝
""")
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--port",default=PORT,type=int)
    p.add_argument("--capital",default=CAPITAL,type=float)
    a=p.parse_args(); run(a.port,a.capital)
