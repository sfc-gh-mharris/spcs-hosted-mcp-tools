// Entrypoint. Configured by PORT, HOST, MCP_SERVER_URL.
import { buildMonitor } from './monitor.js';

const port = Number.parseInt(process.env.PORT ?? '8080', 10);
const host = process.env.HOST ?? '0.0.0.0';
const mcpServerUrl = process.env.MCP_SERVER_URL ?? 'http://localhost:8000/mcp';

const log = (msg, extra = {}) => console.log(JSON.stringify({ ts: new Date().toISOString(), msg, ...extra }));

const monitor = buildMonitor({
  mcpServerUrl,
  // One line per call so SPCS service logs can be compared with the server's.
  onCall: (e) => log('call', { id: e.id, source: e.source, args: e.args, ok: e.ok, result: e.result, error: e.error, ms: e.latencyMs }),
});

const url = await monitor.listen(port, host);
log('listening', { url, mcpServerUrl });

// Connect once at startup so the logs show whether the MCP server is reachable.
try {
  const { tools } = await monitor.mcp.listTools();
  log('mcp connected', { server: monitor.mcp.status.serverInfo, protocol: monitor.mcp.status.protocolVersion, tools: tools.map((t) => t.name) });
} catch (err) {
  log('mcp not reachable yet', { error: err.message });
}

const shutdown = async (signal) => {
  log('shutting down', { signal });
  await monitor.close();
  process.exit(0);
};
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
