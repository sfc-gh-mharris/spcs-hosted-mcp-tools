// In-process MCP server built with the Node SDK, so client tests do not need Python.
import http from 'node:http';
import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

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
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on('close', () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });
  app.all('/mcp', (req, res) => res.status(405).end());

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
