// Runs any MCP tool call as a background job recorded in the call log.
// The browser never waits on a tool: start() returns a running entry at once, so a slow
// Cortex call cannot be cut by the 90 s SPCS ingress idle timeout.
import { performance } from 'node:perf_hooks';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';

export const DEFAULT_TIMEOUT_MS = 120_000;
export const LONG_TIMEOUT_MS = 15 * 60_000; // DATA_AGENT_RUN's synchronous limit
const LONG_TOOLS = new Set(['ask_agent', 'ask_coding_agent', 'coco_task']);

export const timeoutFor = (tool, overrides = {}) =>
  overrides[tool] ?? (LONG_TOOLS.has(tool) ? LONG_TIMEOUT_MS : DEFAULT_TIMEOUT_MS);

const textOf = (result) =>
  (result.content ?? [])
    .filter((c) => c.type === 'text')
    .map((c) => c.text)
    .join('\n');

// Servers wrap primitive returns as {result: value}; show the value itself.
function valueOf(result) {
  const structured = result.structuredContent;
  if (structured && typeof structured === 'object') {
    const keys = Object.keys(structured);
    return keys.length === 1 && keys[0] === 'result' ? structured.result : structured;
  }
  return textOf(result);
}

function errorKindOf(err) {
  if (err instanceof McpError) return err.code === ErrorCode.RequestTimeout ? 'timeout' : 'protocol';
  return 'transport';
}

export function createToolRunner({ mcp, log, timeouts = {} }) {
  let inFlight = 0;

  async function finish(entry, tool, args) {
    const started = performance.now();
    const elapsed = () => Math.round((performance.now() - started) * 100) / 100;
    inFlight++;
    try {
      const result = await mcp.callTool(tool, args, { timeoutMs: timeoutFor(tool, timeouts) });
      if (result.isError) {
        return log.update(entry.id, { status: 'done', ok: false, errorKind: 'tool', error: textOf(result), latencyMs: elapsed() });
      }
      return log.update(entry.id, { status: 'done', ok: true, result: valueOf(result), latencyMs: elapsed() });
    } catch (err) {
      return log.update(entry.id, {
        status: 'done',
        ok: false,
        errorKind: errorKindOf(err),
        error: err?.message ?? String(err),
        latencyMs: elapsed(),
      });
    } finally {
      inFlight--;
    }
  }

  return {
    start(tool, args, source) {
      const entry = log.append({ source, tool, args, status: 'running', ok: null });
      return { entry, done: finish(entry, tool, args) };
    },
    run(tool, args, source) {
      return this.start(tool, args, source).done;
    },
    running: () => inFlight,
  };
}
