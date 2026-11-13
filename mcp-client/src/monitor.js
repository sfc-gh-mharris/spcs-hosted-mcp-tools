// Wires the MCP connection, call log, traffic generator, and HTTP app together.
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createApp } from './app.js';
import { createAddCaller } from './caller.js';
import { CallLog } from './callLog.js';
import { McpConnection } from './mcpClient.js';
import { TrafficGenerator } from './traffic.js';

const PUBLIC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');

export function buildMonitor({ mcpServerUrl, onCall, publicDir = PUBLIC_DIR }) {
  const mcp = new McpConnection({ url: mcpServerUrl });
  const log = new CallLog({ onAppend: onCall });
  const callAdd = createAddCaller({ mcp, log });
  const traffic = new TrafficGenerator({ call: callAdd });
  const app = createApp({ mcp, log, traffic, callAdd, publicDir });
  const server = http.createServer(app);

  return {
    mcp,
    log,
    traffic,
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
