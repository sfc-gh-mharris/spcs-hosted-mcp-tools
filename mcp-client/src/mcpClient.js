// Thin wrapper over the MCP SDK client: lazy connect, reconnect after transport failures,
// and a status snapshot the UI can show.
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { McpError } from '@modelcontextprotocol/sdk/types.js';

export class McpConnection {
  #client = null;
  #transport = null;
  #connecting = null;

  constructor({ url, timeoutMs = 10000, clientInfo = { name: 'spcs-mcp-monitor', version: '0.1.0' } }) {
    this.url = url;
    this.timeoutMs = timeoutMs;
    this.clientInfo = clientInfo;
    this.status = { url, connected: false, serverInfo: null, protocolVersion: null, connectedAt: null, lastError: null };
  }

  listTools() {
    return this.#run((client) => client.listTools(undefined, { timeout: this.timeoutMs }));
  }

  callTool(name, args) {
    return this.#run((client) => client.callTool({ name, arguments: args }, undefined, { timeout: this.timeoutMs }));
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
    const transport = new StreamableHTTPClientTransport(new URL(this.url));
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
