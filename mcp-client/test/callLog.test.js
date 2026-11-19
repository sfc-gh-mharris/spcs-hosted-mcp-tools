import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CallLog } from '../src/callLog.js';

const entry = (over = {}) => ({
  source: 'manual',
  tool: 'add',
  args: { a: 1, b: 2 },
  ok: true,
  result: 3,
  latencyMs: 10,
  ...over,
});

test('append assigns increasing ids and an ISO timestamp', () => {
  const log = new CallLog();
  const first = log.append(entry());
  const second = log.append(entry());
  assert.equal(first.id, 1);
  assert.equal(second.id, 2);
  assert.ok(!Number.isNaN(Date.parse(first.ts)));
});

test('caps at capacity, dropping the oldest entries', () => {
  const log = new CallLog({ capacity: 3 });
  for (let i = 0; i < 5; i++) log.append(entry());
  assert.deepEqual(log.since(0).map((e) => e.id), [3, 4, 5]);
});

test('since(id) returns only newer entries', () => {
  const log = new CallLog();
  for (let i = 0; i < 4; i++) log.append(entry());
  assert.deepEqual(log.since(2).map((e) => e.id), [3, 4]);
  assert.deepEqual(log.since(4), []);
});

test('stats report all-time totals and latency over retained entries', () => {
  const log = new CallLog({ capacity: 20 });
  for (let ms = 1; ms <= 20; ms++) log.append(entry({ latencyMs: ms, ok: ms % 10 !== 0 }));
  const stats = log.stats();
  assert.equal(stats.total, 20);
  assert.equal(stats.errors, 2);
  assert.equal(stats.avgMs, 10.5);
  assert.equal(stats.p95Ms, 19);
});

test('totals keep counting after old entries are evicted', () => {
  const log = new CallLog({ capacity: 2 });
  for (let i = 0; i < 5; i++) log.append(entry({ ok: false }));
  assert.equal(log.stats().total, 5);
  assert.equal(log.stats().errors, 5);
  assert.equal(log.since(0).length, 2);
});

test('stats on an empty log', () => {
  assert.deepEqual(new CallLog().stats(), { total: 0, errors: 0, running: 0, avgMs: null, p95Ms: null, lastId: 0, lastRev: 0 });
});

test('onAppend hook receives each stored entry', () => {
  const seen = [];
  const log = new CallLog({ onAppend: (e) => seen.push(e.id) });
  log.append(entry());
  log.append(entry());
  assert.deepEqual(seen, [1, 2]);
});

test('update changes an entry in place and bumps its revision', () => {
  const log = new CallLog();
  const running = log.append({ source: 'manual', tool: 'slow', args: {}, status: 'running' });
  log.append(entry());
  const revBefore = log.stats().lastRev;
  const done = log.update(running.id, { status: 'done', ok: true, result: 'x', latencyMs: 5 });
  assert.equal(done.id, running.id);
  assert.equal(done.ok, true);
  assert.ok(done.rev > revBefore);
  assert.deepEqual(log.sinceRev(revBefore).map((e) => e.id), [running.id]);
  assert.equal(log.since(0).length, 2);
});

test('running entries count separately and stay out of latency and error stats', () => {
  const log = new CallLog();
  const running = log.append({ source: 'manual', tool: 'slow', args: {}, status: 'running' });
  log.append(entry({ latencyMs: 10 }));
  assert.equal(log.stats().running, 1);
  assert.equal(log.stats().avgMs, 10);
  log.update(running.id, { status: 'done', ok: false, error: 'boom', latencyMs: 30 });
  const stats = log.stats();
  assert.equal(stats.running, 0);
  assert.equal(stats.errors, 1);
  assert.equal(stats.avgMs, 20);
});

test('update of an evicted entry is a no-op', () => {
  const log = new CallLog({ capacity: 1 });
  const first = log.append(entry());
  log.append(entry());
  assert.equal(log.update(first.id, { ok: false }), null);
});
