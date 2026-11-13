# MCP server and client as two Snowpark Container Services

One SPCS service hosts an MCP server, a second SPCS service is an MCP client that calls its tools over the SPCS internal network, and a browser UI on the client lets you watch the calls. The tool is deliberately trivial (`add(a, b)`) so the interesting parts are the plumbing: MCP over Streamable HTTP between containers, service DNS, private versus public endpoints, and ingress auth.

```
Browser --HTTPS + Snowflake login--> MCP_CLIENT  (Node/Express :8080, public endpoint "ui")
                                        |
                                        |  MCP Streamable HTTP (JSON-RPC)
                                        v  http://mcp-server:8000/mcp
                                     MCP_SERVER  (Python MCP SDK :8000, private endpoint "mcp")
```

The browser never reaches the MCP server. The Node backend holds the MCP client connection, records every call, and serves the UI.

## What is here

| Path | Contents |
|---|---|
| `mcp-server/` | Python MCP server (`mcp` SDK 2.3, `MCPServer`), `add` tool, `/healthz`, and a `probe` CLI that smoke-tests any MCP URL |
| `mcp-client/` | Node MCP client (`@modelcontextprotocol/sdk` 1.32), Express API, call log, traffic generator, static monitor UI |
| `compose.yaml` | Both images on one Docker network, using the same hostnames as SPCS; the server is not exposed to the host |
| `spcs/` | Setup SQL, service specs, probe job, suspend, resume, teardown |
| `scripts/` | Build and push, rolling deploy, local and SPCS smoke tests |
| `.snowflake/cortex/plans/` | The staged, test-gated plan this was built from |

## Prerequisites

- Docker with `linux/amd64` builds (SPCS runs amd64 only; Apple Silicon builds under emulation)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/), Node 22+
- Snowflake CLI with a connection to an account that has SPCS. Every script takes the connection from `SNOW_CONNECTION`:

```bash
export SNOW_CONNECTION=<your snow CLI connection name>
```

## Run the tests locally

```bash
cd mcp-server && uv run pytest                      # 15 tests: tool, MCP over HTTP, host-header checks, probe
cd mcp-client && npm install && npm test            # 23 tests against an in-process fake MCP server

# Node client against the real Python server
(cd mcp-server && HOST=127.0.0.1 PORT=8765 uv run python -m mcp_server) &
cd mcp-client && MCP_SERVER_URL=http://127.0.0.1:8765/mcp node --test test/e2e.test.js
```

Both containers together, with the same hostnames SPCS uses:

```bash
bash scripts/smoke_local.sh          # KEEP_UP=1 leaves the stack running at http://localhost:8080
```

## Deploy to SPCS

1. Create the role, database, image repository, compute pool, and grants (run as ACCOUNTADMIN; the pool starts suspended):

   ```bash
   snow sql -c "$SNOW_CONNECTION" -f spcs/00_setup.sql
   ```

2. Build and push both images:

   ```bash
   bash scripts/build_push.sh v1
   ```

3. Create the server with `spcs/mcp-server.spec.yaml` (private endpoint), then prove container-to-container MCP with the probe job before adding any UI:

   ```sql
   USE ROLE MCP_DEMO_ROLE;
   CREATE SERVICE MCP_SPCS_DEMO.APP.MCP_SERVER IN COMPUTE POOL MCP_DEMO_POOL
     FROM SPECIFICATION $$ <contents of spcs/mcp-server.spec.yaml> $$;
   ```

   `spcs/run_probe.sql` runs the probe as an `EXECUTE JOB SERVICE` and reads both sides' logs. Expect `PROBE PASSED`.

4. Create the client the same way with `spcs/mcp-client.spec.yaml` (public endpoint). Get the URL with `SHOW ENDPOINTS IN SERVICE MCP_SPCS_DEMO.APP.MCP_CLIENT`; provisioning takes a few minutes.

5. Test the public endpoint programmatically with a PAT (from `SNOWFLAKE_PAT`, or the `token` field of your connection in `~/.snowflake/connections.toml`; never printed):

   ```bash
   python3 scripts/smoke_spcs.py               # tools, add(2, 3), connection status
   python3 scripts/smoke_spcs.py --soak 180    # traffic for 3 minutes, past the 90 s ingress idle timeout
   ```

Open the ingress URL in a browser and sign in with your Snowflake user to use the monitor.

## Operate

```bash
bash scripts/build_push.sh v2 && bash scripts/deploy.sh client v2   # rolling update; ingress URL is kept
snow sql -c "$SNOW_CONNECTION" -f spcs/suspend.sql                   # stop billing
snow sql -c "$SNOW_CONNECTION" -f spcs/resume.sql                    # bring it back
snow sql -c "$SNOW_CONNECTION" -f spcs/99_teardown.sql               # remove everything
```

## Things we learned building it

- **Auto-resume only reacts to ingress.** A suspended service with `AUTO_RESUME = TRUE` wakes when its public endpoint gets a request, but not when another service calls it. With the monitor tab open, a plain `SUSPEND` woke the client and the pool within 20 seconds while the server stayed down, so you paid for a node and the UI reported the MCP server as unreachable. `spcs/suspend.sql` turns `AUTO_RESUME` off first; `spcs/resume.sql` restores it.
- **MCP Python SDK 2.x renamed FastMCP to `MCPServer`** (`from mcp.server.mcpserver import MCPServer`), and host and port move to run time. Its DNS-rebinding protection switches on only when bound to localhost, so in a container it is off unless you configure it. The server passes an explicit allow-list (`MCP_ALLOWED_HOSTS`, default includes `mcp-server:*`) and a test proves an unknown `Host` gets 421.
- **Protocol versions differ by SDK and both work.** The Python client negotiates `2026-07-28`; the Node SDK 1.32 uses the `2025-11-25` initialize handshake. The server accepts both.
- **`/mcp` cannot be the readiness probe.** It does not answer a plain GET with 200, so both services expose `/healthz`, and the client's health check does not depend on the server being up.
- **Same-schema services resolve by short name.** `MCP_SERVER` is reachable as `mcp-server:8000`; the full name is `mcp-server.<hash>.svc.spcs.internal`.
- **A default role of ACCOUNTADMIN did not block ingress** for either PAT or browser sign-in in our account.
