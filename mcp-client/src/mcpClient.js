// Thin wrapper over the MCP SDK client: lazy connect, reconnect after transport failures,
// and a status snapshot the UI can show.
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { McpError } from '@modelcontextprotocol/sdk/types.js';
import { Agent, fetch as undiciFetch } from 'undici';

// Node's fetch gives up after 300 s without response headers. The server answers tool calls
// with one JSON response, so a 15-minute agent run needs a longer limit on this hop.
const longFetchDispatcher = new Agent({ headersTimeout: 16 * 60_000, bodyTimeout: 16 * 60_000 });
const longFetch = (url, init) => undiciFetch(url, { ...init, dispatcher: longFetchDispatcher });

export class McpConnection {
  #client = null;
  #transport = null;
  #connecting = null;

  constructor({ url, timeoutMs = 10000, clientInfo = { name: 'spcs-mcp-monitor', version: '0.2.0' } }) {
    this.url = url;
    this.timeoutMs = timeoutMs;
    this.clientInfo = clientInfo;
    this.status = { url, connected: false, serverInfo: null, protocolVersion: null, connectedAt: null, lastError: null };
  }

  listTools() {
    return this.#run((client) => client.listTools(undefined, { timeout: this.timeoutMs }));
  }

  callTool(name, args, { timeoutMs = this.timeoutMs } = {}) {
    return this.#run((client) =>
      client.callTool({ name, arguments: args }, undefined, { timeout: timeoutMs, maxTotalTimeout: timeoutMs }),
    );
  }

  async close() {
    await this.#drop();
  }

  async #run(fn) {
    try {
      return await fn(await this.#ensureConnected());
    } catch (err) {
      // A JSON-RPC error means the server answered; anything else means the link is suspect.
      if (!(err instanceof McpError)) await this.#drop(err);
      throw err;
    }
  }

  #ensureConnected() {
    if (this.#client) return Promise.resolve(this.#client);
    this.#connecting ??= this.#connect().finally(() => {
      this.#connecting = null;
    });
    return this.#connecting;
  }

  async #connect() {
    const client = new Client(this.clientInfo);
    const transport = new StreamableHTTPClientTransport(new URL(this.url), { fetch: longFetch });
    await client.connect(transport, { timeout: this.timeoutMs });
    this.#client = client;
    this.#transport = transport;
    this.status = {
      ...this.status,
      connected: true,
      serverInfo: client.getServerVersion() ?? null,
      protocolVersion: transport.protocolVersion ?? null,
      connectedAt: new Date().toISOString(),
      lastError: null,
    };
    return client;
  }

  async #drop(err) {
    const client = this.#client;
    this.#client = null;
    this.#transport = null;
    this.status = { ...this.status, connected: false, lastError: err ? err.message : this.status.lastError };
    if (client) await client.close().catch(() => {});
  }
}
