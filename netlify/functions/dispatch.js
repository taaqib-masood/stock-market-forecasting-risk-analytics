// Netlify Function — serverless trigger for the trading workflow.
//
// The dashboard's "Run controls" buttons POST here instead of talking to an
// always-on server. This function holds the GitHub token (Netlify env var, never
// in the browser) and fires a workflow_dispatch on the trading_pipeline workflow.
// GitHub Actions then runs the scan/auto-close, commits dashboard_data.js, and the
// push redeploys this site — so a click refreshes live data with zero servers.
//
// Required Netlify env vars (Site settings → Environment variables):
//   GH_DISPATCH_TOKEN  classic PAT with the "repo" scope
//   GH_OWNER           e.g. "taaqib-masood"
//   GH_REPO            e.g. "stock-market-forecasting-risk-analytics"
// Optional:
//   GH_WORKFLOW (default "trading_pipeline.yml"), GH_REF (default "V-1.0")
//
// job === "research-backtest" also requires { ticker, years } in the body —
// these become workflow_dispatch inputs, validated here before they ever
// reach the Actions run.

const ALLOWED = new Set(["nightly-scan", "auto-close", "weekly-backtest", "research-backtest"]);
const TICKER_RE = /^[A-Za-z0-9.&-]{1,15}$/;

function resp(statusCode, body) {
  return {
    statusCode,
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
    body: JSON.stringify(body),
  };
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return resp(204, {});
  if (event.httpMethod !== "POST") return resp(405, { error: "POST only" });

  let body;
  try { body = JSON.parse(event.body || "{}"); }
  catch { return resp(400, { error: "invalid JSON body" }); }
  const { job, ticker, years } = body;
  if (!ALLOWED.has(job)) return resp(400, { error: `job must be one of ${[...ALLOWED].join(", ")}` });

  const inputs = { job };
  if (job === "research-backtest") {
    if (!ticker || !TICKER_RE.test(ticker)) return resp(400, { error: "ticker must match ^[A-Za-z0-9.&-]{1,15}$" });
    const y = parseInt(years, 10);
    if (!Number.isInteger(y) || y < 1 || y > 15) return resp(400, { error: "years must be an integer 1-15" });
    inputs.ticker = ticker.toUpperCase();
    inputs.years = String(y);
  }

  const token = process.env.GH_DISPATCH_TOKEN;
  const owner = process.env.GH_OWNER;
  const repo = process.env.GH_REPO;
  const wf = process.env.GH_WORKFLOW || "trading_pipeline.yml";
  const ref = process.env.GH_REF || "V-1.0";
  if (!token || !owner || !repo) {
    return resp(500, { error: "server not configured: set GH_DISPATCH_TOKEN, GH_OWNER, GH_REPO" });
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
    });
  }
  const text = await r.text();
  return resp(502, { ok: false, status: r.status, error: text.slice(0, 300) });
};
