// Wires the MCP connection, call log, job runner, traffic generator, and HTTP app together.
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createApp } from './app.js';
import { CallLog } from './callLog.js';
import { createToolRunner } from './jobs.js';
import { McpConnection } from './mcpClient.js';
import { TrafficGenerator } from './traffic.js';

const PUBLIC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');

// The server's inbound call log lives next to /mcp on its private port.
export const inboundUrlFor = (mcpServerUrl) => new URL('/calls', mcpServerUrl).toString();

export function buildMonitor({ mcpServerUrl, inboundUrl = inboundUrlFor(mcpServerUrl), onCall, publicDir = PUBLIC_DIR }) {
  const mcp = new McpConnection({ url: mcpServerUrl });
  // onCall fires when an entry finishes, which is when it has a result worth logging.
  const log = new CallLog({
    onAppend: (e) => e.status === 'done' && onCall?.(e),
    onUpdate: (e) => e.status === 'done' && onCall?.(e),
  });
  const runner = createToolRunner({ mcp, log });
  // Traffic is hard-wired to add so it can never spend credits on Cortex tools.
  const callAdd = (a, b, source) => runner.run('add', { a, b }, source);
  const traffic = new TrafficGenerator({ call: callAdd });
  const app = createApp({ mcp, log, traffic, runner, callAdd, inboundUrl, publicDir });
  const server = http.createServer(app);

  return {
    mcp,
    log,
    traffic,
    runner,
    listen(port, host) {
      return new Promise((resolve) => {
        server.listen(port, host, () => resolve(`http://${host}:${server.address().port}`));
      });
    },
    async close() {
      traffic.stop();
      await mcp.close();
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}
