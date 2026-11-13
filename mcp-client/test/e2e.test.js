// Runs against a real MCP server (the Python one) only when MCP_SERVER_URL is set.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { buildMonitor } from '../src/monitor.js';

const url = process.env.MCP_SERVER_URL;
const opts = { skip: url ? false : 'set MCP_SERVER_URL to run against a real MCP server' };

let monitor;
let base;

before(async () => {
  if (!url) return;
  monitor = buildMonitor({ mcpServerUrl: url });
  base = await monitor.listen(0, '127.0.0.1');
});

after(async () => {
  if (monitor) await monitor.close();
});

test('real server lists add', opts, async () => {
  const body = await (await fetch(`${base}/api/tools`)).json();
  assert.ok(body.tools.some((t) => t.name === 'add'));
});

test('real server computes add(2, 3) = 5', opts, async () => {
  const res = await fetch(`${base}/api/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ a: 2, b: 3 }),
  });
  const body = await res.json();
  assert.equal(res.status, 200, JSON.stringify(body));
  assert.equal(body.result, 5);
});

test('real server identifies itself', opts, async () => {
  const body = await (await fetch(`${base}/api/status`)).json();
  assert.equal(body.connected, true);
  assert.equal(body.serverInfo.name, 'spcs-add-server');
});
