"""
Web Dashboard — localhost:5000
==============================
Plain Python HTTP server + inline HTML. No frameworks.
Access from any device on the same WiFi.

Run: python -m src.web_dashboard
     python -m src.web_dashboard --port 5000 --capital 50000
"""

import json
import os
import threading
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PORT     = int(os.environ.get("WEB_PORT", 5000))
CAPITAL  = float(os.environ.get("WEBHOOK_CAPITAL", 50_000))

# ── API helpers ───────────────────────────────────────────────────────────────

def _api_portfolio():
    from src.paper_trader import _load, portfolio_value, trade_stats
    state = _load()
    pv    = portfolio_value(state)
    stats = trade_stats(state)
    return {"portfolio": pv, "stats": stats, "trades": state["trades"][-20:]}


def _api_signals():
    from src.scanner import scan
    from src.earnings_guard import filter_cards
    cards = scan(capital=CAPITAL, top_n=5)
    safe, blocked = filter_cards(cards, days=5)
    return {
        "signals":  safe[:3],
        "blocked":  blocked,
        "scanned_at": datetime.now().strftime("%H:%M:%S"),
    }


def _api_log_trade(ticker: str, shares: int, price: float):
    from src.paper_trader import _load, buy
    state = _load()
    return buy(ticker.upper(), shares, price, state=state)


def _api_close_trade(ticker: str, price: float):
    from src.paper_trader import _load, sell
    state = _load()
    return sell(ticker.upper(), price=price, state=state)


# ── HTML page ─────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSE Trade Intelligence</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --blue: #58a6ff; --cyan: #39d353; --text: #e6edf3;
    --muted: #8b949e; --card: #1c2128;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', monospace; font-size: 14px; }
  .header { background: var(--surface); border-bottom: 1px solid var(--border);
            padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 18px; color: var(--blue); }
  .header .meta { color: var(--muted); font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 12px; padding: 20px 24px 0; }
  .stat-card { background: var(--card); border: 1px solid var(--border);
               border-radius: 8px; padding: 16px; }
  .stat-card .label { color: var(--muted); font-size: 11px; text-transform: uppercase;
                      letter-spacing: 0.8px; margin-bottom: 6px; }
  .stat-card .value { font-size: 22px; font-weight: 700; }
  .stat-card .sub   { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .green { color: var(--green); } .red { color: var(--red); }
  .yellow { color: var(--yellow); } .blue { color: var(--blue); }
  .section { margin: 20px 24px; }
  .section h2 { font-size: 14px; color: var(--muted); text-transform: uppercase;
                letter-spacing: 1px; margin-bottom: 12px; border-bottom: 1px solid var(--border);
                padding-bottom: 8px; }
  .signal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
  .signal-card { background: var(--card); border: 1px solid var(--border);
                 border-radius: 8px; padding: 16px; position: relative; }
  .signal-card .ticker { font-size: 18px; font-weight: 700; color: var(--blue); }
  .signal-card .score-bar { background: var(--border); border-radius: 4px;
                             height: 6px; margin: 8px 0; overflow: hidden; }
  .signal-card .score-fill { height: 100%; border-radius: 4px; background: var(--green); }
  .signal-card .row { display: flex; justify-content: space-between;
                      padding: 4px 0; border-bottom: 1px solid var(--border); }
  .signal-card .row:last-of-type { border: none; }
  .signal-card .lbl { color: var(--muted); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
           font-size: 11px; font-weight: 600; }
  .badge-buy  { background: rgba(63,185,80,0.15); color: var(--green); }
  .badge-sell { background: rgba(248,81,73,0.15);  color: var(--red); }
  .badge-wait { background: rgba(210,153,34,0.15); color: var(--yellow); }
  .badge-bull { background: rgba(63,185,80,0.15);  color: var(--green); }
  .badge-bear { background: rgba(248,81,73,0.15);  color: var(--red); }
  .badge-side { background: rgba(210,153,34,0.15); color: var(--yellow); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase;
       letter-spacing: 0.8px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
  tr:hover td { background: var(--surface); }
  .btn { background: var(--blue); color: #000; border: none; border-radius: 6px;
         padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer; }
  .btn:hover { opacity: 0.85; }
  .btn-red { background: var(--red); color: #fff; }
  .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
           z-index: 100; align-items: center; justify-content: center; }
  .modal.open { display: flex; }
  .modal-box { background: var(--surface); border: 1px solid var(--border);
               border-radius: 10px; padding: 24px; min-width: 320px; }
  .modal-box h3 { margin-bottom: 16px; }
  .modal-box input { background: var(--bg); border: 1px solid var(--border);
                     color: var(--text); border-radius: 6px; padding: 8px 12px;
                     width: 100%; margin-bottom: 10px; font-size: 14px; }
  .modal-box .actions { display: flex; gap: 8px; margin-top: 8px; }
  .spinner { display: inline-block; width: 14px; height: 14px;
             border: 2px solid var(--border); border-top-color: var(--blue);
             border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { color: var(--muted); text-align: center; padding: 32px; }
  .tag { font-size: 11px; background: var(--border); border-radius: 4px;
         padding: 2px 6px; margin: 2px; display: inline-block; }
  .tag-confirm { background: rgba(63,185,80,0.2); color: var(--green); }
  .refresh-btn { background: none; border: 1px solid var(--border); color: var(--muted);
                 border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer; }
  .refresh-btn:hover { border-color: var(--blue); color: var(--blue); }
  @media (max-width: 600px) { .grid { grid-template-columns: 1fr 1fr; }
    .section { margin: 12px; } }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📈 NSE Trade Intelligence</h1>
    <div class="meta" id="last-update">Loading...</div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;">
    <span id="regime-badge" class="badge">—</span>
    <button class="refresh-btn" onclick="loadAll()">↻ Refresh</button>
  </div>
</div>

<!-- Summary cards -->
<div class="grid" id="summary-grid">
  <div class="stat-card"><div class="label">Portfolio Value</div>
    <div class="value" id="s-total">—</div><div class="sub" id="s-pnl">—</div></div>
  <div class="stat-card"><div class="label">Cash Available</div>
    <div class="value" id="s-cash">—</div><div class="sub">available to deploy</div></div>
  <div class="stat-card"><div class="label">Win Rate</div>
    <div class="value" id="s-wr">—</div><div class="sub" id="s-trades">— trades</div></div>
  <div class="stat-card"><div class="label">Profit Factor</div>
    <div class="value" id="s-pf">—</div><div class="sub" id="s-pnl-total">—</div></div>
</div>

<!-- Signals -->
<div class="section">
  <h2>Today's Signals <span id="scan-time" style="font-size:11px;margin-left:8px;"></span>
    <button class="refresh-btn" style="float:right" onclick="loadSignals()">
      <span id="scan-spinner" style="display:none" class="spinner"></span> Rescan
    </button>
  </h2>
  <div class="signal-grid" id="signals-container">
    <div class="empty">Loading signals...</div>
  </div>
</div>

<!-- Open positions -->
<div class="section">
  <h2>Open Positions</h2>
  <div id="positions-container">
    <div class="empty">No open positions</div>
  </div>
</div>

<!-- Trade history -->
<div class="section">
  <h2>Trade History</h2>
  <table>
    <thead><tr>
      <th>Ticker</th><th>Shares</th><th>Entry</th><th>Exit</th>
      <th>P&L</th><th>Result</th><th>Date</th>
    </tr></thead>
    <tbody id="history-body"><tr><td colspan="7" class="empty">No closed trades</td></tr></tbody>
  </table>
</div>

<!-- Log Trade Modal -->
<div class="modal" id="log-modal">
  <div class="modal-box">
    <h3>Log Trade</h3>
    <input id="lt-ticker" placeholder="Ticker (e.g. RELIANCE)" />
    <input id="lt-shares" placeholder="Shares" type="number" />
    <input id="lt-price"  placeholder="Entry price" type="number" step="0.01" />
    <div class="actions">
      <button class="btn" onclick="submitLog()">Log Trade</button>
      <button class="refresh-btn" onclick="closeModal('log-modal')">Cancel</button>
    </div>
    <div id="lt-result" style="margin-top:10px;font-size:12px;color:var(--green)"></div>
  </div>
</div>

<!-- Close Trade Modal -->
<div class="modal" id="close-modal">
  <div class="modal-box">
    <h3>Close Position</h3>
    <input id="ct-ticker" placeholder="Ticker" />
    <input id="ct-price"  placeholder="Exit price" type="number" step="0.01" />
    <div class="actions">
      <button class="btn btn-red" onclick="submitClose()">Close Trade</button>
      <button class="refresh-btn" onclick="closeModal('close-modal')">Cancel</button>
    </div>
    <div id="ct-result" style="margin-top:10px;font-size:12px;"></div>
  </div>
</div>

<div class="section" style="text-align:right;padding-bottom:24px;">
  <button class="btn" onclick="document.getElementById('log-modal').classList.add('open')">
    + Log Trade
  </button>
  &nbsp;
  <button class="btn btn-red" onclick="document.getElementById('close-modal').classList.add('open')">
    Close Position
  </button>
</div>

<script>
const fmt = (n, dec=2) => '₹' + parseFloat(n).toLocaleString('en-IN', {minimumFractionDigits:dec, maximumFractionDigits:dec});
const pct  = n => (n >= 0 ? '+' : '') + parseFloat(n).toFixed(2) + '%';
const col  = n => parseFloat(n) >= 0 ? 'green' : 'red';

async function loadPortfolio() {
  const r = await fetch('/api/portfolio');
  const d = await r.json();
  const p = d.portfolio, s = d.stats;

  document.getElementById('s-total').textContent = fmt(p.total_val);
  document.getElementById('s-total').className   = 'value ' + col(p.total_pnl);
  document.getElementById('s-pnl').textContent   = pct(p.total_pnl_pct) + ' total return';
  document.getElementById('s-cash').textContent  = fmt(p.cash);
  document.getElementById('s-wr').textContent    = s.win_rate ? s.win_rate + '%' : '—';
  document.getElementById('s-wr').className      = 'value ' + (s.win_rate >= 55 ? 'green' : s.win_rate >= 45 ? 'yellow' : 'red');
  document.getElementById('s-trades').textContent = (s.total || 0) + ' closed trades';
  document.getElementById('s-pf').textContent    = s.profit_factor || '—';
  document.getElementById('s-pf').className      = 'value ' + (s.profit_factor >= 1.5 ? 'green' : 'yellow');
  document.getElementById('s-pnl-total').textContent = s.total_pnl ? fmt(s.total_pnl) + ' total' : '—';

  // Open positions
  const pc = document.getElementById('positions-container');
  if (!p.marked || Object.keys(p.marked).length === 0) {
    pc.innerHTML = '<div class="empty">No open positions</div>';
  } else {
    let html = '<table><thead><tr><th>Ticker</th><th>Shares</th><th>Avg Entry</th><th>Current</th><th>Value</th><th>Unrealised</th><th>Stop</th><th>Target</th></tr></thead><tbody>';
    for (const [t, m] of Object.entries(p.marked)) {
      const uc = m.unrealised >= 0 ? 'green' : 'red';
      html += `<tr><td><b>${t}</b></td><td>${m.shares}</td><td>${fmt(m.avg_entry)}</td>
               <td>${fmt(m.current_price)}</td><td>${fmt(m.market_value)}</td>
               <td class="${uc}">${fmt(m.unrealised)} (${pct(m.unrealised_pct)})</td>
               <td class="red">${m.stop ? fmt(m.stop) : '—'}</td>
               <td class="green">${m.target ? fmt(m.target) : '—'}</td></tr>`;
    }
    html += '</tbody></table>';
    pc.innerHTML = html;
  }

  // Trade history
  const tb = document.getElementById('history-body');
  if (!d.trades || d.trades.length === 0) {
    tb.innerHTML = '<tr><td colspan="7" class="empty">No closed trades yet</td></tr>';
  } else {
    tb.innerHTML = [...d.trades].reverse().map(t => {
      const pc = t.pnl > 0 ? 'green' : 'red';
      return `<tr><td><b>${t.ticker}</b></td><td>${t.shares}</td>
              <td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td>
              <td class="${pc}">${fmt(t.pnl)} (${pct(t.pnl_pct)})</td>
              <td><span class="badge ${t.outcome==='WIN'?'badge-buy':'badge-sell'}">${t.outcome}</span></td>
              <td>${t.closed_at?.slice(0,10) || '—'}</td></tr>`;
    }).join('');
  }
}

async function loadSignals() {
  document.getElementById('scan-spinner').style.display = 'inline-block';
  document.getElementById('signals-container').innerHTML = '<div class="empty"><span class="spinner"></span> Scanning NSE... (~20s)</div>';
  const r = await fetch('/api/signals');
  const d = await r.json();
  document.getElementById('scan-spinner').style.display = 'none';
  document.getElementById('scan-time').textContent = 'scanned at ' + d.scanned_at;

  const sc = document.getElementById('signals-container');
  if (!d.signals || d.signals.length === 0) {
    sc.innerHTML = '<div class="empty">No high-conviction signals today.<br><small>Market may be bearish. Check again tomorrow.</small></div>';
    return;
  }
  sc.innerHTML = d.signals.map((c, i) => {
    const sp  = ((c.stop  / c.entry - 1)*100).toFixed(1);
    const tp  = ((c.target/ c.entry - 1)*100).toFixed(1);
    const mtf = c.mtf_confirmed ? '<span class="tag tag-confirm">✓ MTF</span>' : '<span class="tag">— MTF</span>';
    const bt  = c.backtest ? `<span class="tag tag-confirm">✓ BT ${c.backtest.win_rate}%</span>` : '';
    return `
    <div class="signal-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span class="ticker">#${i+1} ${c.ticker}</span>
        <span class="badge badge-buy">${c.signal}</span>
      </div>
      <div class="score-bar"><div class="score-fill" style="width:${c.score}%"></div></div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:8px">Score: ${c.score}/100 ${mtf} ${bt}</div>
      <div class="row"><span class="lbl">Entry</span>  <b>${fmt(c.entry)}</b></div>
      <div class="row"><span class="lbl">Stop</span>   <span class="red">${fmt(c.stop)} (${sp}%)</span></div>
      <div class="row"><span class="lbl">Target</span> <span class="green">${fmt(c.target)} (+${tp}%)</span></div>
      <div class="row"><span class="lbl">R:R</span>    <span class="green">${c.rr} : 1</span></div>
      <div class="row"><span class="lbl">Shares</span> ${c.shares} &nbsp; <span class="lbl">Invest</span> ${fmt(c.invest, 0)}</div>
      <div class="row"><span class="lbl">Risk</span>   <span class="red">${fmt(c.risk_rs, 0)}</span> &nbsp;
                       <span class="lbl">Reward</span> <span class="green">${fmt(c.reward_rs, 0)}</span></div>
      <div class="row"><span class="lbl">RSI</span> ${c.rsi} &nbsp; <span class="lbl">Vol</span> ${c.vol_surge}x &nbsp; <span class="lbl">5d</span> ${c.ret_5d > 0 ? '+' : ''}${c.ret_5d}%</div>
      <div style="margin-top:8px">
        <button class="btn" style="font-size:11px;padding:4px 10px"
          onclick="prefillLog('${c.ticker}',${c.shares},${c.entry})">Log this trade</button>
      </div>
    </div>`;
  }).join('');
}

async function loadRegime() {
  try {
    const r = await fetch('/api/regime');
    const d = await r.json();
    const b = document.getElementById('regime-badge');
    b.textContent = d.emoji + ' ' + d.regime + '  Nifty ₹' + parseInt(d.nifty).toLocaleString('en-IN');
    b.className = 'badge badge-' + d.regime.toLowerCase().slice(0,4);
  } catch(e) {}
}

function prefillLog(ticker, shares, price) {
  document.getElementById('lt-ticker').value = ticker;
  document.getElementById('lt-shares').value = shares;
  document.getElementById('lt-price').value  = price;
  document.getElementById('log-modal').classList.add('open');
}

async function submitLog() {
  const ticker = document.getElementById('lt-ticker').value.trim().toUpperCase();
  const shares = parseInt(document.getElementById('lt-shares').value);
  const price  = parseFloat(document.getElementById('lt-price').value);
  if (!ticker || !shares || !price) { return; }
  const r = await fetch('/api/log_trade', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ticker, shares, price})
  });
  const d = await r.json();
  const el = document.getElementById('lt-result');
  if (d.ok) {
    el.textContent = '✓ Logged: ' + ticker + ' ' + shares + ' @ ₹' + price;
    el.style.color = 'var(--green)';
    setTimeout(() => { closeModal('log-modal'); loadPortfolio(); }, 1200);
  } else {
    el.textContent = '✗ ' + d.reason;
    el.style.color = 'var(--red)';
  }
}

async function submitClose() {
  const ticker = document.getElementById('ct-ticker').value.trim().toUpperCase();
  const price  = parseFloat(document.getElementById('ct-price').value);
  if (!ticker || !price) return;
  const r = await fetch('/api/close_trade', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ticker, price})
  });
  const d = await r.json();
  const el = document.getElementById('ct-result');
  if (d.ok) {
    const pc = d.pnl > 0 ? 'var(--green)' : 'var(--red)';
    el.style.color = pc;
    el.textContent = '✓ Closed ' + ticker + '  P&L: ₹' + d.pnl.toFixed(2);
    setTimeout(() => { closeModal('close-modal'); loadPortfolio(); }, 1200);
  } else {
    el.textContent = '✗ ' + d.reason;
    el.style.color = 'var(--red)';
  }
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

async function loadAll() {
  document.getElementById('last-update').textContent =
    'Updated: ' + new Date().toLocaleTimeString('en-IN');
  await Promise.all([loadPortfolio(), loadRegime()]);
}

// Initial load
loadAll();
loadSignals();

// Auto-refresh portfolio every 60s
setInterval(loadPortfolio, 60_000);
</script>
</body>
</html>"""


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence access log

    def _json(self, status: int, data: dict):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._html(HTML)

        elif path == "/api/portfolio":
            try:
                self._json(200, _api_portfolio())
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/signals":
            try:
                self._json(200, _api_signals())
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/regime":
            try:
                import yfinance as yf, numpy as np, contextlib, io
                with contextlib.redirect_stderr(io.StringIO()):
                    df = yf.download("^NSEI", period="60d", interval="1d",
                                     progress=False, auto_adjust=True)
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                c = df["Close"].values.astype(float)
                sma20 = np.mean(c[-20:])
                sma50 = np.mean(c[-50:]) if len(c) >= 50 else sma20
                price = float(c[-1])
                ret1w = (price / c[-6] - 1) * 100 if len(c) >= 6 else 0
                if price > sma20 > sma50 and ret1w > 0:
                    regime, emoji = "BULL", "🟢"
                elif price < sma20 < sma50 and ret1w < 0:
                    regime, emoji = "BEAR", "🔴"
                else:
                    regime, emoji = "SIDEWAYS", "🟡"
                self._json(200, {"regime": regime, "emoji": emoji,
                                 "nifty": price, "ret1w": round(ret1w, 2)})
            except Exception as e:
                self._json(200, {"regime": "UNKNOWN", "emoji": "❓",
                                 "nifty": 0, "error": str(e)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/log_trade":
            try:
                r = _api_log_trade(body["ticker"], int(body["shares"]),
                                   float(body["price"]))
                self._json(200, r)
            except Exception as e:
                self._json(500, {"ok": False, "reason": str(e)})

        elif path == "/api/close_trade":
            try:
                r = _api_close_trade(body["ticker"], float(body["price"]))
                self._json(200, r)
            except Exception as e:
                self._json(500, {"ok": False, "reason": str(e)})
        else:
            self._json(404, {"error": "not found"})


# ── Main ──────────────────────────────────────────────────────────────────────

def run(port: int = PORT, capital: float = CAPITAL):
    global CAPITAL
    CAPITAL = capital
    server  = HTTPServer(("0.0.0.0", port), Handler)

    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print(f"""
╔══════════════════════════════════════════════════════╗
║         NSE Trade Intelligence — Web Dashboard      ║
╠══════════════════════════════════════════════════════╣
║  Local   : http://localhost:{port}                     ║
║  Network : http://{local_ip}:{port}                ║
║  Capital : ₹{capital:,.0f}                              ║
╠══════════════════════════════════════════════════════╣
║  Open either URL in your browser or phone (same WiFi)║
║  Press Ctrl+C to stop                               ║
╚══════════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",    default=PORT,    type=int)
    parser.add_argument("--capital", default=CAPITAL, type=float)
    args = parser.parse_args()
    run(port=args.port, capital=args.capital)
