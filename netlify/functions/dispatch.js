// Netlify Function — serverless trigger for the trading workflow.
//
// The dashboard's "Run controls" buttons POST here instead of talking to an
// always-on server. This function holds the GitHub token (Netlify env var, never
// in the browser) and fires a workflow_dispatch on the trading_pipeline workflow.
// GitHub Actions then runs the scan/auto-close, commits dashboard_data.js, and the
// push redeploys this site — so a click refreshes live data with zero servers.
//
// Required Netlify env vars (Site settings → Environment variables):
//   GH_DISPATCH_TOKEN  fine-grained PAT limited to this repo (Actions: read+write);
//                      a classic PAT with the "repo" scope works but is broader
//   GH_OWNER           e.g. "taaqib-masood"
//   GH_REPO            e.g. "stock-market-forecasting-risk-analytics"
//   DISPATCH_SECRET    shared passphrase — callers must send it as the
//                      X-Dispatch-Secret header or a "secret" body field.
//                      If unset, the function refuses every request (fail closed).
// Optional:
//   GH_WORKFLOW (default "trading_pipeline.yml"), GH_REF (default "V-1.0")
//   DISPATCH_ALLOWED_ORIGIN  comma-separated origins allowed to call this from a
//                      browser cross-origin (e.g. "https://yoursite.netlify.app").
//                      Unset = no CORS headers at all: same-origin dashboard calls
//                      still work, cross-origin browser calls are blocked.
//
// job === "research-backtest" also requires { ticker, years } in the body —
// these become workflow_dispatch inputs, validated here before they ever
// reach the Actions run.

const crypto = require("crypto");

const ALLOWED = new Set(["nightly-scan", "auto-close", "weekly-backtest", "research-backtest"]);
const TICKER_RE = /^[A-Za-z0-9.&-]{1,15}$/;
const ALLOWED_ORIGINS = new Set(
  (process.env.DISPATCH_ALLOWED_ORIGIN || "").split(",").map(s => s.trim()).filter(Boolean)
);

// Best-effort per-instance rate limit (Netlify functions are ephemeral, so this
// only throttles bursts hitting a warm instance).
const RATE_LIMIT = 30, RATE_WINDOW_MS = 60_000;
const hits = new Map(); // ip -> { n, reset }
function rateOk(ip) {
  const now = Date.now();
  const e = hits.get(ip);
  if (!e || now > e.reset) { hits.set(ip, { n: 1, reset: now + RATE_WINDOW_MS }); return true; }
  return ++e.n <= RATE_LIMIT;
}

function resp(statusCode, body, origin) {
  const headers = { "Content-Type": "application/json", "Vary": "Origin" };
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Access-Control-Allow-Headers"] = "Content-Type, X-Dispatch-Secret";
    headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
  }
  return { statusCode, headers, body: JSON.stringify(body) };
}

function validSecret(event, body) {
  const expected = process.env.DISPATCH_SECRET;
  if (!expected) return false;
  const supplied = String(event.headers["x-dispatch-secret"] || (body && body.secret) || "");
  const a = Buffer.from(supplied), b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

exports.handler = async (event) => {
  const origin = event.headers.origin || event.headers.Origin || "";
  if (event.httpMethod === "OPTIONS") return resp(204, {}, origin);
  if (event.httpMethod !== "POST") return resp(405, { error: "POST only" }, origin);

  let body;
  try { body = JSON.parse(event.body || "{}"); }
  catch { return resp(400, { error: "invalid JSON body" }, origin); }

  if (!process.env.DISPATCH_SECRET) {
    return resp(500, { error: "server not configured: set DISPATCH_SECRET" }, origin);
  }
  if (!validSecret(event, body)) {
    return resp(401, { error: "missing/invalid dispatch secret" }, origin);
  }

  const ip = event.headers["x-nf-client-connection-ip"] || (event.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  if (!rateOk(ip)) return resp(429, { error: "rate limit exceeded" }, origin);

  const { job, ticker, years } = body;
  if (!ALLOWED.has(job)) return resp(400, { error: `job must be one of ${[...ALLOWED].join(", ")}` }, origin);

  const inputs = { job };
  if (job === "research-backtest") {
    if (!ticker || !TICKER_RE.test(ticker)) return resp(400, { error: "ticker must match ^[A-Za-z0-9.&-]{1,15}$" }, origin);
    const y = parseInt(years, 10);
    if (!Number.isInteger(y) || y < 1 || y > 15) return resp(400, { error: "years must be an integer 1-15" }, origin);
    inputs.ticker = ticker.toUpperCase();
    inputs.years = String(y);
  }

  const token = process.env.GH_DISPATCH_TOKEN;
  const owner = process.env.GH_OWNER;
  const repo = process.env.GH_REPO;
  const wf = process.env.GH_WORKFLOW || "trading_pipeline.yml";
  const ref = process.env.GH_REF || "V-1.0";
  if (!token || !owner || !repo) {
    return resp(500, { error: "server not configured: set GH_DISPATCH_TOKEN, GH_OWNER, GH_REPO" }, origin);
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${wf}/dispatches`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": "boro-dashboard",
    },
    body: JSON.stringify({ ref, inputs }),
  });

  if (r.status === 204) {
    return resp(200, {
      ok: true, job, dispatched: true,
      note: job === "research-backtest"
        ? `GitHub Actions run started for ${inputs.ticker} — backtest takes longer (~3–8 min), check back on this tab.`
        : "GitHub Actions run started — data refreshes when it finishes (~1–3 min).",
    }, origin);
  }
  const text = await r.text();
  return resp(502, { ok: false, status: r.status, error: text.slice(0, 300) }, origin);
};
