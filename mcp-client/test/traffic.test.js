import { test, mock, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { TrafficGenerator } from '../src/traffic.js';

// Let any promise callbacks scheduled by a timer tick settle.
const flush = () => new Promise((resolve) => setImmediate(resolve));

async function advance(ms, step = 1000) {
  for (let t = 0; t < ms; t += step) {
    mock.timers.tick(step);
    await flush();
  }
}

beforeEach(() => mock.timers.enable({ apis: ['setInterval'] }));
afterEach(() => mock.timers.reset());

test('calls at the configured interval with traffic source and integer args', async () => {
  const calls = [];
  const gen = new TrafficGenerator({ call: async (a, b, source) => calls.push({ a, b, source }) });
  gen.start(1000);
  await advance(3000);
  gen.stop();
  assert.equal(calls.length, 3);
  for (const c of calls) {
    assert.equal(c.source, 'traffic');
    assert.ok(Number.isInteger(c.a) && c.a >= 0 && c.a < 100);
    assert.ok(Number.isInteger(c.b) && c.b >= 0 && c.b < 100);
  }
});

test('stop halts further calls', async () => {
  let count = 0;
  const gen = new TrafficGenerator({ call: async () => count++ });
  gen.start(1000);
  await advance(2000);
  gen.stop();
  await advance(3000);
  assert.equal(count, 2);
  assert.equal(gen.status().enabled, false);
});

test('interval is clamped to the allowed range', () => {
  const gen = new TrafficGenerator({ call: async () => {} });
  gen.start(10);
  assert.equal(gen.status().intervalMs, 500);
  gen.start(10 ** 9);
  assert.equal(gen.status().intervalMs, 60000);
  gen.stop();
});

test('restarting with a new interval replaces the old timer', async () => {
  let count = 0;
  const gen = new TrafficGenerator({ call: async () => count++ });
  gen.start(1000);
  gen.start(5000);
  await advance(4000);
  assert.equal(count, 0);
  await advance(1000);
  assert.equal(count, 1);
  gen.stop();
});

test('skips a tick while the previous call is still in flight', async () => {
  let release;
  let count = 0;
  const gen = new TrafficGenerator({
    call: () => {
      count++;
      return new Promise((resolve) => (release = resolve));
    },
  });
  gen.start(1000);
  await advance(3000);
  assert.equal(count, 1);
  assert.equal(gen.status().skipped, 2);
  release();
  await flush();
  await advance(1000);
  assert.equal(count, 2);
  gen.stop();
});

test('status reports sent count', async () => {
  const gen = new TrafficGenerator({ call: async () => {} });
  gen.start(1000);
  await advance(2000);
  assert.deepEqual(gen.status(), { enabled: true, intervalMs: 1000, sent: 2, skipped: 0 });
  gen.stop();
});
