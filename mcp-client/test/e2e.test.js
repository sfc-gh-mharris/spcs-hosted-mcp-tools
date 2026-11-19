// Runs against a real MCP server (the Python one) only when MCP_SERVER_URL is set.
// With E2E_CORTEX=1 (server started with SNOW_CONNECTION) it also runs one real Cortex call.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { buildMonitor } from '../src/monitor.js';

const url = process.env.MCP_SERVER_URL;
const opts = { skip: url ? false : 'set MCP_SERVER_URL to run against a real MCP server' };
const cortexOpts = { skip: url && process.env.E2E_CORTEX ? false : 'set MCP_SERVER_URL and E2E_CORTEX=1' };

let monitor;
let base;

const post = (path, body) =>
  fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function runJob(tool, args, waitMs = 60000) {
  const res = await post('/api/jobs', { tool, args });
  assert.equal(res.status, 202, await res.clone().text());
  const { entry } = await res.json();
  for (const deadline = Date.now() + waitMs; Date.now() < deadline; ) {
    const { entries } = await (await fetch(`${base}/api/calls?sinceRev=0`)).json();
    const current = entries.find((e) => e.id === entry.id);
    if (current?.status === 'done') return current;
    await sleep(200);
  }
  throw new Error(`job ${tool} did not finish in ${waitMs} ms`);
}

before(async () => {
  if (!url) return;
  monitor = buildMonitor({ mcpServerUrl: url });
  base = await monitor.listen(0, '127.0.0.1');
});

after(async () => {
  if (monitor) await monitor.close();
});

test('real server lists add and the Cortex tools', opts, async () => {
  const body = await (await fetch(`${base}/api/tools`)).json();
  const names = body.tools.map((t) => t.name);
  for (const name of ['add', 'cortex_complete', 'cortex_classify', 'cortex_sentiment']) assert.ok(names.includes(name), name);
});

test('real server computes add(2, 3) = 5', opts, async () => {
  const res = await post('/api/call', { a: 2, b: 3 });
  const body = await res.json();
  assert.equal(res.status, 200, JSON.stringify(body));
  assert.equal(body.result, 5);
});

test('real server runs add as a background job', opts, async () => {
  const entry = await runJob('add', { a: 40, b: 2 });
  assert.equal(entry.ok, true);
  assert.equal(entry.result, 42);
});

test('real server identifies itself', opts, async () => {
  const body = await (await fetch(`${base}/api/status`)).json();
  assert.equal(body.connected, true);
  assert.equal(body.serverInfo.name, 'spcs-add-server');
});

test('real server call log is reachable through /api/inbound', opts, async () => {
  const res = await fetch(`${base}/api/inbound?since=0`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.ok(Array.isArray(body.entries));
  assert.ok(body.entries.some((e) => e.endpoint === 'private' && e.tool === 'add'));
});

test('real server classifies text through Cortex', cortexOpts, async () => {
  const entry = await runJob('cortex_classify', { text: 'My card was charged twice', categories: ['billing', 'shipping'] });
  assert.equal(entry.ok, true, entry.error);
  assert.equal(entry.result.label, 'billing');
  assert.ok(entry.result.query_id);
});
