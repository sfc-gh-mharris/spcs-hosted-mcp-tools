// In-process MCP server built with the Node SDK, so client tests do not need Python.
// Mirrors the Python server's private port: MCP at /mcp and the inbound call log at /calls.
import http from 'node:http';
import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const FAKE_INBOUND = [
  { id: 1, ts: '2026-11-14T01:10:07Z', endpoint: 'public', tool: 'add', args: { a: 19.5, b: 22.5 }, ok: true, result: { result: 42 }, caller: 'TEST_USER', latency_ms: 0.9 },
];

export async function startFakeMcpServer({ port = 0 } = {}) {
  const state = { toolCalls: 0 };
  const app = express();
  app.use(express.json());

  app.post('/mcp', async (req, res) => {
    // Stateless: a fresh server and transport per request, like the Python server.
    const server = new McpServer({ name: 'fake-add-server', version: '0.0.0' });
    server.registerTool(
      'add',
      {
        description: 'Add two numbers and return the sum.',
        inputSchema: { a: z.number(), b: z.number() },
        outputSchema: { result: z.number() },
      },
      async ({ a, b }) => {
        state.toolCalls++;
        return { content: [{ type: 'text', text: String(a + b) }], structuredContent: { result: a + b } };
      },
    );
    server.registerTool(
      'slow_echo',
      {
        description: 'Wait delayMs, then echo text. Stands in for slow Cortex tools.',
        inputSchema: { text: z.string(), delayMs: z.number().int().min(0).max(10000) },
        outputSchema: { echo: z.string() },
      },
      async ({ text, delayMs }) => {
        state.toolCalls++;
        await sleep(delayMs);
        return { content: [{ type: 'text', text }], structuredContent: { echo: text } };
      },
    );
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on('close', () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });
  app.all('/mcp', (req, res) => res.status(405).end());

  app.get('/calls', (req, res) => {
    const since = Number.parseInt(req.query.since ?? '0', 10) || 0;
    res.json({ entries: FAKE_INBOUND.filter((e) => e.id > since), last_id: FAKE_INBOUND.length });
  });

  const httpServer = http.createServer(app);
  await new Promise((resolve) => httpServer.listen(port, '127.0.0.1', resolve));
  const actualPort = httpServer.address().port;

  return {
    state,
    port: actualPort,
    url: `http://127.0.0.1:${actualPort}/mcp`,
    close: () =>
      new Promise((resolve) => {
        httpServer.closeAllConnections();
        httpServer.close(resolve);
      }),
  };
}
