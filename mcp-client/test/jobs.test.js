import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { CallLog } from '../src/callLog.js';
import { DEFAULT_TIMEOUT_MS, LONG_TIMEOUT_MS, createToolRunner, timeoutFor } from '../src/jobs.js';

const fakeMcp = (impl) => {
  const calls = [];
  return {
    calls,
    callTool: (name, args, opts) => {
      calls.push({ name, args, opts });
      return impl(name, args, opts);
    },
  };
};

test('start returns a running entry at once, then completes it in place', async () => {
  let release;
  const mcp = fakeMcp(() => new Promise((resolve) => (release = resolve)));
  const log = new CallLog();
  const runner = createToolRunner({ mcp, log });

  const { entry, done } = runner.start('cortex_complete', { prompt: 'hi' }, 'manual');
  assert.equal(entry.status, 'running');
  assert.equal(log.stats().running, 1);

  release({ content: [{ type: 'text', text: '{"text":"hello"}' }], structuredContent: { text: 'hello', query_id: 'q1' } });
  const finished = await done;
  assert.equal(finished.id, entry.id);
  assert.equal(finished.status, 'done');
  assert.equal(finished.ok, true);
  assert.deepEqual(finished.result, { text: 'hello', query_id: 'q1' });
  assert.equal(typeof finished.latencyMs, 'number');
});

test('primitive results wrapped as {result} are unwrapped', async () => {
  const mcp = fakeMcp(async () => ({ content: [{ type: 'text', text: '5' }], structuredContent: { result: 5 } }));
  const entry = await createToolRunner({ mcp, log: new CallLog() }).run('add', { a: 2, b: 3 }, 'manual');
  assert.equal(entry.result, 5);
});

test('text-only results fall back to the text content', async () => {
  const mcp = fakeMcp(async () => ({ content: [{ type: 'text', text: 'plain' }] }));
  const entry = await createToolRunner({ mcp, log: new CallLog() }).run('t', {}, 'manual');
  assert.equal(entry.result, 'plain');
});

test('tool errors are recorded with kind tool', async () => {
  const mcp = fakeMcp(async () => ({ isError: true, content: [{ type: 'text', text: 'Snowflake error 002003' }] }));
  const entry = await createToolRunner({ mcp, log: new CallLog() }).run('t', {}, 'manual');
  assert.equal(entry.ok, false);
  assert.equal(entry.errorKind, 'tool');
  assert.match(entry.error, /002003/);
});

test('request timeouts are recorded with kind timeout', async () => {
  const mcp = fakeMcp(async () => {
    throw new McpError(ErrorCode.RequestTimeout, 'Request timed out');
  });
  const entry = await createToolRunner({ mcp, log: new CallLog() }).run('t', {}, 'manual');
  assert.equal(entry.errorKind, 'timeout');
});

test('transport failures are recorded with kind transport', async () => {
  const mcp = fakeMcp(async () => {
    throw new TypeError('fetch failed');
  });
  const entry = await createToolRunner({ mcp, log: new CallLog() }).run('t', {}, 'manual');
  assert.equal(entry.errorKind, 'transport');
});

test('each call gets its tool timeout', async () => {
  const mcp = fakeMcp(async () => ({ content: [], structuredContent: { result: 1 } }));
  const runner = createToolRunner({ mcp, log: new CallLog(), timeouts: { custom: 1234 } });
  await runner.run('custom', {}, 'manual');
  await runner.run('add', {}, 'manual');
  await runner.run('ask_agent', {}, 'manual');
  assert.deepEqual(mcp.calls.map((c) => c.opts.timeoutMs), [1234, DEFAULT_TIMEOUT_MS, LONG_TIMEOUT_MS]);
});

test('timeoutFor gives agent and coding tools the long budget', () => {
  assert.equal(timeoutFor('add'), DEFAULT_TIMEOUT_MS);
  for (const tool of ['ask_agent', 'ask_coding_agent', 'coco_task']) assert.equal(timeoutFor(tool), LONG_TIMEOUT_MS);
});

test('running count tracks in-flight jobs', async () => {
  let release;
  const mcp = fakeMcp(() => new Promise((resolve) => (release = resolve)));
  const runner = createToolRunner({ mcp, log: new CallLog() });
  const { done } = runner.start('t', {}, 'manual');
  assert.equal(runner.running(), 1);
  release({ content: [], structuredContent: { result: 1 } });
  await done;
  assert.equal(runner.running(), 0);
});
