// Times one add() call over MCP and records it in the call log.
import { performance } from 'node:perf_hooks';
import { McpError } from '@modelcontextprotocol/sdk/types.js';

const textOf = (result) =>
  (result.content ?? [])
    .filter((c) => c.type === 'text')
    .map((c) => c.text)
    .join('\n');

export function createAddCaller({ mcp, log, tool = 'add' }) {
  return async function callAdd(a, b, source) {
    const base = { source, tool, args: { a, b } };
    const started = performance.now();
    const elapsed = () => Math.round((performance.now() - started) * 100) / 100;
    try {
      const result = await mcp.callTool(tool, { a, b });
      if (result.isError) {
        return log.append({ ...base, ok: false, errorKind: 'tool', error: textOf(result), latencyMs: elapsed() });
      }
      const value = result.structuredContent?.result ?? Number(textOf(result));
      return log.append({ ...base, ok: true, result: value, latencyMs: elapsed() });
    } catch (err) {
      // McpError: the server answered with a JSON-RPC error. Anything else: network or HTTP failure.
      const errorKind = err instanceof McpError ? 'protocol' : 'transport';
      return log.append({ ...base, ok: false, errorKind, error: err?.message ?? String(err), latencyMs: elapsed() });
    }
  };
}
