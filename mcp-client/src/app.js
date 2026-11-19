// HTTP API and static UI for the monitor. The browser only talks to this app;
// this app is the MCP client.
import express from 'express';

const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const intParam = (v) => {
  const n = Number.parseInt(v ?? '0', 10);
  return Number.isNaN(n) ? 0 : n;
};

export function createApp({ mcp, log, traffic, runner, callAdd, inboundUrl, publicDir }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '64kb' }));

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

  // Synchronous add, kept for the smoke tests and scripts that predate jobs.
  app.post('/api/call', async (req, res) => {
    const { a, b } = req.body ?? {};
    if (!isNumber(a) || !isNumber(b)) {
      return res.status(400).json({ ok: false, error: 'a and b must both be finite numbers' });
    }
    const entry = await callAdd(a, b, 'manual');
    const status = entry.ok ? 200 : entry.errorKind === 'transport' ? 502 : 422;
    res.status(status).json({ ok: entry.ok, result: entry.result, error: entry.error, latencyMs: entry.latencyMs, entry });
  });

  // Any discovered tool, run in the background. Poll /api/calls?sinceRev= for the outcome.
  app.post('/api/jobs', async (req, res) => {
    const { tool, args = {} } = req.body ?? {};
    if (typeof tool !== 'string' || !tool || !isPlainObject(args)) {
      return res.status(400).json({ error: 'expected { tool: string, args?: object }' });
    }
    let tools;
    try {
      ({ tools } = await mcp.listTools());
    } catch (err) {
      return res.status(502).json({ error: err.message });
    }
    if (!tools.some((t) => t.name === tool)) {
      return res.status(404).json({ error: `the MCP server has no tool named ${tool}` });
    }
    const { entry } = runner.start(tool, args, 'manual');
    res.status(202).json({ entry });
  });

  app.get('/api/calls', (req, res) => {
    const entries = req.query.sinceRev !== undefined ? log.sinceRev(intParam(req.query.sinceRev)) : log.since(intParam(req.query.since));
    res.json({ entries, stats: log.stats() });
  });

  // What Snowflake (CoCo, Cortex Agents) called on the server's public endpoint.
  app.get('/api/inbound', async (req, res) => {
    try {
      const upstream = await fetch(`${inboundUrl}?since=${intParam(req.query.since)}`, { signal: AbortSignal.timeout(5000) });
      if (!upstream.ok) return res.status(502).json({ error: `server call log returned HTTP ${upstream.status}` });
      res.json(await upstream.json());
    } catch (err) {
      res.status(502).json({ error: err.message });
    }
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
