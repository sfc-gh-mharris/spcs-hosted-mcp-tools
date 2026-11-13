// HTTP API and static UI for the monitor. The browser only talks to this app;
// this app is the MCP client.
import express from 'express';

const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);

export function createApp({ mcp, log, traffic, callAdd, publicDir }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '16kb' }));

  // Readiness must not depend on the MCP server, so the UI can come up and report it as down.
  app.get('/healthz', (req, res) => res.json({ status: 'ok' }));

  app.get('/api/status', (req, res) => {
    res.json({ ...mcp.status, traffic: traffic.status(), stats: log.stats() });
  });

  app.get('/api/tools', async (req, res) => {
    try {
      const { tools } = await mcp.listTools();
      res.json({ tools });
    } catch (err) {
      res.status(502).json({ error: err.message });
    }
  });

  app.post('/api/call', async (req, res) => {
    const { a, b } = req.body ?? {};
    if (!isNumber(a) || !isNumber(b)) {
      return res.status(400).json({ ok: false, error: 'a and b must both be finite numbers' });
    }
    const entry = await callAdd(a, b, 'manual');
    const status = entry.ok ? 200 : entry.errorKind === 'transport' ? 502 : 422;
    res.status(status).json({ ok: entry.ok, result: entry.result, error: entry.error, latencyMs: entry.latencyMs, entry });
  });

  app.get('/api/calls', (req, res) => {
    const since = Number.parseInt(req.query.since ?? '0', 10);
    res.json({ entries: log.since(Number.isNaN(since) ? 0 : since), stats: log.stats() });
  });

  app.get('/api/traffic', (req, res) => res.json(traffic.status()));

  app.post('/api/traffic', (req, res) => {
    const { enabled, intervalMs } = req.body ?? {};
    if (typeof enabled !== 'boolean' || (intervalMs !== undefined && !isNumber(intervalMs))) {
      return res.status(400).json({ error: 'expected { enabled: boolean, intervalMs?: number }' });
    }
    if (enabled) traffic.start(intervalMs);
    else traffic.stop();
    res.json(traffic.status());
  });

  if (publicDir) app.use(express.static(publicDir));
  return app;
}
