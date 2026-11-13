import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startFakeMcpServer } from './fakeMcpServer.js';
import { buildMonitor } from '../src/monitor.js';

let fake;
let monitor;
let base;

const json = async (path, init) => {
  const res = await fetch(`${base}${path}`, init);
  return { status: res.status, body: await res.json() };
};
const post = (path, body) =>
  json(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

before(async () => {
  fake = await startFakeMcpServer();
  monitor = buildMonitor({ mcpServerUrl: fake.url });
  base = await monitor.listen(0, '127.0.0.1');
});

after(async () => {
  await monitor.close();
  await fake.close();
});

test('GET /healthz is ok without touching MCP', async () => {
  const { status, body } = await json('/healthz');
  assert.equal(status, 200);
  assert.equal(body.status, 'ok');
});

test('GET /api/status reports the server URL before any call', async () => {
  const { body } = await json('/api/status');
  assert.equal(body.url, fake.url);
  assert.equal(body.connected, false);
});

test('GET /api/tools lists add with its input schema', async () => {
  const { status, body } = await json('/api/tools');
  assert.equal(status, 200);
  const add = body.tools.find((t) => t.name === 'add');
  assert.ok(add);
  assert.deepEqual(Object.keys(add.inputSchema.properties).sort(), ['a', 'b']);
});

test('GET /api/status shows connected server info after a call', async () => {
  const { body } = await json('/api/status');
  assert.equal(body.connected, true);
  assert.equal(body.serverInfo.name, 'fake-add-server');
  assert.ok(body.protocolVersion);
});

test('POST /api/call returns the sum and logs one entry with latency', async () => {
  const before = (await json('/api/calls?since=0')).body.stats.lastId;
  const { status, body } = await post('/api/call', { a: 2, b: 3 });
  assert.equal(status, 200);
  assert.equal(body.ok, true);
  assert.equal(body.result, 5);
  const calls = (await json(`/api/calls?since=${before}`)).body.entries;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].source, 'manual');
  assert.deepEqual(calls[0].args, { a: 2, b: 3 });
  assert.ok(typeof calls[0].latencyMs === 'number');
});

test('POST /api/call rejects non-numeric input without calling MCP', async () => {
  const toolCallsBefore = fake.state.toolCalls;
  for (const bad of [{ a: 'x', b: 1 }, { a: 1 }, { a: '2', b: 3 }, { a: null, b: 1 }]) {
    const { status } = await post('/api/call', bad);
    assert.equal(status, 400, JSON.stringify(bad));
  }
  assert.equal(fake.state.toolCalls, toolCallsBefore);
});

test('unreachable server returns 502 and logs a failure, then recovers on restart', async () => {
  const port = fake.port;
  await fake.close();

  const down = await post('/api/call', { a: 1, b: 1 });
  assert.equal(down.status, 502);
  assert.equal(down.body.ok, false);
  assert.equal(down.body.entry.errorKind, 'transport');
  assert.equal((await json('/api/status')).body.connected, false);

  fake = await startFakeMcpServer({ port });
  const up = await post('/api/call', { a: 1, b: 1 });
  assert.equal(up.status, 200);
  assert.equal(up.body.result, 2);
});

test('traffic generator produces traffic entries until disabled', async () => {
  const start = (await json('/api/calls?since=0')).body.stats.lastId;
  const on = await post('/api/traffic', { enabled: true, intervalMs: 500 });
  assert.equal(on.status, 200);
  assert.equal(on.body.enabled, true);

  await sleep(1300);
  const off = await post('/api/traffic', { enabled: false });
  assert.equal(off.body.enabled, false);

  const entries = (await json(`/api/calls?since=${start}`)).body.entries;
  assert.ok(entries.length >= 2, `expected >= 2 traffic calls, got ${entries.length}`);
  assert.ok(entries.every((e) => e.source === 'traffic' && e.ok));

  const settled = (await json('/api/calls?since=0')).body.stats.lastId;
  await sleep(800);
  assert.equal((await json('/api/calls?since=0')).body.stats.lastId, settled);
});

test('POST /api/traffic validates its body', async () => {
  assert.equal((await post('/api/traffic', { enabled: 'yes' })).status, 400);
  assert.equal((await post('/api/traffic', { enabled: true, intervalMs: 'fast' })).status, 400);
  await post('/api/traffic', { enabled: false });
});

test('serves the monitor UI', async () => {
  const res = await fetch(`${base}/`);
  assert.equal(res.status, 200);
  assert.match(await res.text(), /MCP Monitor/);
});
