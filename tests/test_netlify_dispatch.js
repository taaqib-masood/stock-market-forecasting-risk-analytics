"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { handler } = require("../netlify/functions/dispatch");

test("workflow dispatch requires a session token and keeps the GitHub token server-side", async () => {
  const names = ["DISPATCH_TOKEN", "GH_DISPATCH_TOKEN", "GH_OWNER", "GH_REPO", "GH_WORKFLOW", "GH_REF"];
  const previous = Object.fromEntries(names.map((name) => [name, process.env[name]]));
  const originalFetch = global.fetch;
  const calls = [];

  for (const name of names) delete process.env[name];
  process.env.GH_DISPATCH_TOKEN = "github-test-token";
  process.env.GH_OWNER = "example";
  process.env.GH_REPO = "repo";
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return { status: 204, text: async () => "" };
  };

  try {
    const body = JSON.stringify({ job: "auto-close" });
    const unconfigured = await handler({ httpMethod: "POST", headers: {}, body });
    assert.equal(unconfigured.statusCode, 500);
    assert.equal(calls.length, 0);

    process.env.DISPATCH_TOKEN = "d".repeat(32);
    const anonymous = await handler({ httpMethod: "POST", headers: {}, body });
    const incorrect = await handler({ httpMethod: "POST", headers: { authorization: "Bearer wrong" }, body });
    assert.equal(anonymous.statusCode, 401);
    assert.equal(incorrect.statusCode, 401);
    assert.equal(calls.length, 0);

    const authorized = await handler({
      httpMethod: "POST",
      headers: { authorization: `Bearer ${process.env.DISPATCH_TOKEN}` },
      body,
    });
    assert.equal(authorized.statusCode, 200);
    assert.equal(authorized.headers["Access-Control-Allow-Origin"], undefined);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://api.github.com/repos/example/repo/actions/workflows/trading_pipeline.yml/dispatches");
    assert.equal(calls[0].options.headers.Authorization, "Bearer github-test-token");
    assert.deepEqual(JSON.parse(calls[0].options.body), { ref: "V-1.0", inputs: { job: "auto-close" } });
  } finally {
    global.fetch = originalFetch;
    for (const name of names) {
      if (previous[name] === undefined) delete process.env[name];
      else process.env[name] = previous[name];
    }
  }
});
