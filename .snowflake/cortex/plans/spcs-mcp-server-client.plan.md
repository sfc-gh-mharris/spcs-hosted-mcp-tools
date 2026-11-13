# Plan: SPCS-hosted MCP server with a Node monitor client

Two Snowpark Container Services, a Python MCP server exposing `add(a, b)` and a Node client with a monitor UI, built in seven test-gated stages that move from local code to containers to Snowflake.

## Bottom line

We prove each layer on its own before stacking the next one. Python server locally, then the Node client locally, then both in Docker Compose using SPCS-style hostnames, then the server alone in SPCS verified by an in-cluster probe job, and finally the client with its public UI. Every stage ends with a test gate, and the next stage does not start until that gate passes. The first stage that touches Snowflake is Stage 4, so nothing bills until the local stack works.

## Decisions

| Area | Choice |
|---|---|
| Location | New database `MCP_SPCS_DEMO`, schema `APP`, image repo `IMAGES`, new pool `MCP_DEMO_POOL` (CPU_X64_XS, 1 node, created suspended, auto-suspend 600s) |
| Owner | `MCP_DEMO_ROLE` owns both services; granted to the deploying user and to `SYSADMIN` so ACCOUNTADMIN inherits it |
| MCP | Official SDKs on both sides: `mcp` (FastMCP) in Python, `@modelcontextprotocol/sdk` in Node. Streamable HTTP transport, server runs stateless with JSON responses |
| UI | Manual call form with call log, tool discovery panel, traffic generator. Express serving plain HTML/JS, polling every 2s |
| Tests | pytest for the server, `node --test` for the client, shell smoke scripts for Compose and SPCS |
| CLI | Every `snow` command passes `-c $SNOW_CONNECTION` explicitly, so the target account never depends on the CLI's default connection |
| Images | Built with `--platform linux/amd64`; versioned tags (`v1`, `v2`) so `ALTER SERVICE` picks up changes predictably |

## Architecture

```
Browser --HTTPS + Snowflake login--> MCP_CLIENT  (Node/Express :8080, public endpoint "ui")
                                        |
                                        |  MCP Streamable HTTP (JSON-RPC)
                                        v  http://mcp-server:8000/mcp
                                     MCP_SERVER  (Python FastMCP :8000, private endpoint "mcp")
```

The browser never talks to the MCP server. The Node backend holds the MCP client connection, records every call, and serves the UI. Both services share a schema, so the client reaches the server by its short DNS name `mcp-server`, and the shared owner role grants endpoint access without extra service-role grants.

## Project layout

```
SPCS_HOSTED_MCP_TOOLS/
  mcp-server/
    pyproject.toml, uv.lock
    src/mcp_server/tools.py        # pure add() function
    src/mcp_server/server.py       # FastMCP app, add tool, /healthz route, stdout call logging
    src/mcp_server/__main__.py     # entrypoint: python -m mcp_server
    src/mcp_server/probe.py        # CLI smoke test: python -m mcp_server.probe --url <mcp url>
    tests/test_tools.py
    tests/test_mcp_http.py
    tests/test_probe.py
    Dockerfile
  mcp-client/
    package.json, package-lock.json
    src/index.js                   # boots app from env
    src/app.js                     # Express app factory (testable)
    src/mcpClient.js               # SDK wrapper: lazy connect, listTools, callTool, reconnect, status
    src/callLog.js                 # in-memory ring buffer + stats
    src/traffic.js                 # interval-based traffic generator
    public/index.html, app.js, style.css
    test/callLog.test.js, traffic.test.js, api.test.js, e2e.test.js
    test/fakeMcpServer.js          # in-process MCP server built with the Node SDK
    Dockerfile
  compose.yaml
  scripts/build_push.sh, smoke_local.sh, smoke_spcs.sh
  spcs/00_setup.sql, mcp-server.spec.yaml, probe-job.spec.yaml, mcp-client.spec.yaml,
       suspend.sql, resume.sql, 99_teardown.sql
```

## Contracts

**Tool:** `add(a: number, b: number) -> number`. The input schema requires both arguments as numbers.

**MCP server HTTP**
- `POST /mcp`: MCP Streamable HTTP endpoint
- `GET /healthz`: `{"status":"ok","instance":"<hostname>"}`, used by the SPCS readiness probe because `/mcp` does not answer a plain GET with 200

**MCP client HTTP**
- `GET /healthz`
- `GET /api/status`: connected flag, server URL, server name/version, protocol version, last error
- `GET /api/tools`: result of MCP `tools/list`
- `POST /api/call` body `{a, b}`: validates numbers (400 on bad input, MCP not called), calls `add`, returns `{ok, result, latencyMs}`; 502 if the MCP server is unreachable
- `GET /api/calls?since=<id>`: new log entries plus stats
- `GET /api/traffic`, `POST /api/traffic` body `{enabled, intervalMs}` with interval clamped to 500 to 60000 ms

**Call log entry:** `id, ts, source (manual | traffic), tool, args, result, ok, error, latencyMs`. The ring buffer holds 500 entries and resets on restart, which is fine for a test harness.

---

## Stage 1: MCP server, local Python

**Goal:** a working MCP server on localhost with full test coverage before any container exists.

**Build (tests first):**
1. Scaffold with `uv`, pin the current `mcp` SDK version at build time.
2. Write `tests/test_tools.py`, then implement `tools.add`.
3. Write `tests/test_mcp_http.py` with a fixture that launches `python -m mcp_server` on a free port and polls `/healthz` for up to 10s, then implement `server.py` (bind `0.0.0.0`, `stateless_http=True`, JSON responses, `/healthz` custom route, one log line per tool call).
4. Write `tests/test_probe.py`, then implement `probe.py` (initialize, list tools, call `add(2,3)`, print PASS/FAIL per check, exit 0 or 1).

**Gate (`uv run pytest`):**
- `test_add_integers` 2 + 3 = 5; `test_add_negative_and_float` -1.5 + 1.5 = 0; `test_add_float_precision` 0.1 + 0.2 approx 0.3; `test_add_large_ints`
- `test_healthz_ok`
- `test_initialize_reports_server_name`
- `test_list_tools_has_add_with_numeric_schema`
- `test_call_add_returns_5`
- `test_call_add_missing_arg_is_error`, `test_call_add_non_numeric_is_error`
- `test_non_localhost_host_header`: sends a request with `Host: mcp-server:8000` and expects success. This surfaces the SDK's DNS-rebinding protection now instead of inside SPCS.
- `test_probe_exits_zero_against_running_server`, `test_probe_exits_nonzero_when_unreachable`

## Stage 2: Node client and monitor UI, local

**Goal:** the client and UI work against a fake MCP server first, then against the real Python server.

**Build (tests first):**
1. `callLog.js` from `callLog.test.js`.
2. `traffic.js` from `traffic.test.js` using mocked timers.
3. `test/fakeMcpServer.js`: a small MCP server built with the Node SDK, exposing `add`, startable and stoppable on an ephemeral port. Client tests need no Python.
4. `mcpClient.js` and `app.js` from `api.test.js`.
5. `public/` UI: status banner (connected or not, server URL), tools panel, call form, traffic toggle with interval control, log table with counters (total, errors, average and p95 latency). Polls `/api/calls?since=` every 2s.

**Gate (`npm test`, then a manual browser check):**
- callLog: increasing ids; capped at 500 dropping the oldest; `since(id)` returns only newer entries; stats compute count, errors, average and p95 latency
- traffic: starts calling at the interval; stop halts; interval clamped; entries tagged `traffic`; restarting with a new interval replaces the old timer
- api (against the fake server): `/healthz` 200; `/api/tools` lists `add`; `POST /api/call {2,3}` returns 5 and logs one entry with latency; non-numeric input returns 400 without an MCP call; stopping the fake server makes the next call return 502 and log `ok:false`; restarting the fake server makes the following call succeed (reconnect); enabling traffic produces `traffic` entries and disabling stops them
- e2e (runs only when `MCP_SERVER_URL` is set): against the Stage 1 Python server, tools include `add` and `add(2,3)` returns 5
- Manual: open `http://localhost:8080`, confirm the tools panel, a manual call, and traffic at 1s all show in the log

## Stage 3: Both services in Docker Compose

**Goal:** the exact images we will push run together on a network that mirrors SPCS naming and visibility.

**Build:**
1. `mcp-server/Dockerfile`: `python:3.11-slim`, `uv sync --frozen`, non-root user, `CMD python -m mcp_server`.
2. `mcp-client/Dockerfile`: current Node LTS slim image, `npm ci --omit=dev`, non-root user, `CMD node src/index.js`.
3. `compose.yaml`: both services `platform: linux/amd64`; service names `mcp-server` and `mcp-client`; server port not published to the host (mirrors `public: false`); client `8080:8080`; healthchecks on `/healthz`; client `depends_on` a healthy server; client env `MCP_SERVER_URL=http://mcp-server:8000/mcp`; a `probe` service (server image, probe command) under a profile.
4. `scripts/smoke_local.sh`: build and start, wait for client health, assert `/api/tools` includes `add`, assert `POST /api/call` returns 5, run the probe container against `http://mcp-server:8000/mcp` and require exit 0, tear down.

**Gate:** `smoke_local.sh` passes under amd64 emulation. Re-run the Stage 2 e2e test against the composed server. Record image sizes.

## Stage 4: Snowflake foundation and image push

**Goal:** objects, grants, and images in place with the pool still suspended.

**Build:**
1. `spcs/00_setup.sql` (run as ACCOUNTADMIN):
   - `CREATE ROLE MCP_DEMO_ROLE`; grant it to the current user and to role `SYSADMIN`
   - `CREATE DATABASE MCP_SPCS_DEMO`, transfer ownership to `MCP_DEMO_ROLE`
   - As `MCP_DEMO_ROLE`: `CREATE SCHEMA APP`, `CREATE IMAGE REPOSITORY IMAGES`
   - `CREATE COMPUTE POOL MCP_DEMO_POOL MIN_NODES=1 MAX_NODES=1 INSTANCE_FAMILY=CPU_X64_XS INITIALLY_SUSPENDED=TRUE AUTO_RESUME=TRUE AUTO_SUSPEND_SECS=600`
   - `GRANT USAGE, MONITOR ON COMPUTE POOL MCP_DEMO_POOL TO ROLE MCP_DEMO_ROLE`
   - `GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE MCP_DEMO_ROLE` (required for the client's public endpoint)
2. `scripts/build_push.sh <tag>`: `snow spcs image-registry login -c $SNOW_CONNECTION`, build amd64, tag both images, push to `<org>-<account>.registry.snowflakecomputing.com/mcp_spcs_demo/app/images/`.

**Gate:**
- `SHOW GRANTS TO ROLE MCP_DEMO_ROLE` includes pool USAGE and BIND SERVICE ENDPOINT
- `SHOW COMPUTE POOLS LIKE 'MCP_DEMO_POOL'` shows SUSPENDED
- `SHOW IMAGES IN IMAGE REPOSITORY MCP_SPCS_DEMO.APP.IMAGES` lists `mcp-server:v1` and `mcp-client:v1`

## Stage 5: MCP server in SPCS, verified by a probe job

**Goal:** prove MCP over the SPCS internal network before the Node app or public ingress are involved.

**Build:**
1. `spcs/mcp-server.spec.yaml`: image `/mcp_spcs_demo/app/images/mcp-server:v1`; small resources (about 250m CPU and 256Mi memory requested); `readinessProbe` on port 8000 path `/healthz`; endpoint `mcp`, port 8000, `public: false`.
2. As `MCP_DEMO_ROLE`: `CREATE SERVICE MCP_SERVER IN COMPUTE POOL MCP_DEMO_POOL FROM SPECIFICATION $$...$$ MIN_INSTANCES=1 MAX_INSTANCES=1`.
3. `spcs/probe-job.spec.yaml`: server image with command `python -m mcp_server.probe --url http://mcp-server:8000/mcp`, run with `EXECUTE JOB SERVICE IN COMPUTE POOL MCP_DEMO_POOL NAME=MCP_PROBE_JOB`.

**Gate:**
- `SYSTEM$GET_SERVICE_STATUS('MCP_SERVER')` reports READY
- `SYSTEM$GET_SERVICE_LOGS` shows the server listening on `0.0.0.0:8000`
- `DESCRIBE SERVICE MCP_SERVER` returns a `dns_name` of the form `mcp-server.<hash>.svc.spcs.internal`
- Probe job finishes DONE with all PASS lines in its logs, and the server logs show the matching `add(2,3)` call

## Stage 6: Node client in SPCS with the public UI

**Goal:** the full path from browser to client service to server service.

**Build:**
1. `spcs/mcp-client.spec.yaml`: image `mcp-client:v1`; env `PORT=8080`, `MCP_SERVER_URL=http://mcp-server:8000/mcp`; `readinessProbe` on `/healthz`; endpoint `ui`, port 8080, `public: true`.
2. As `MCP_DEMO_ROLE`: `CREATE SERVICE MCP_CLIENT ...`.
3. `scripts/smoke_spcs.sh`: reads a PAT from an environment variable injected through `secret_env` (never written to disk or the repo), calls `GET /api/tools` and `POST /api/call` on the ingress URL with `Authorization: Snowflake Token="<PAT>"`.

**Gate:**
- MCP_CLIENT READY; logs show a successful MCP connection
- `SHOW ENDPOINTS IN SERVICE MCP_CLIENT` returns an `ingress_url` (provisioning can take a few minutes)
- Browser: sign in, tools panel lists `add`, a manual 2 + 3 returns 5, traffic at 1s keeps the log updating with the page left open for more than 3 minutes (covers the 90s ingress idle timeout), then stop traffic
- `smoke_spcs.sh` passes
- Server log call count matches the client log for the same window
- You confirm the UI works for you

## Stage 7: Update, suspend, resume, teardown

**Goal:** a repeatable way to change, pause, and remove the demo.

**Build:**
1. Update flow: push a new tag with `build_push.sh v2`, then `ALTER SERVICE ... FROM SPECIFICATION` with the new tag. We never drop and recreate MCP_CLIENT, because that changes the ingress URL.
2. `spcs/suspend.sql`: suspend MCP_CLIENT, MCP_SERVER, then the pool. `spcs/resume.sql`: the reverse.
3. `spcs/99_teardown.sql`: drop services, pool, database, and role. Run only when you ask.

**Gate:** after `suspend.sql` the pool reports SUSPENDED; after `resume.sql` both services reach READY and the Stage 5 probe job passes again as a regression check.

---

## Known risks and where each gets caught

| Risk | Caught in | Fallback |
|---|---|---|
| MCP SDK rejects non-localhost `Host` headers (DNS-rebinding protection) | Stage 1 test, confirmed in Stage 3 | Configure the SDK's transport security to allow `mcp-server` and `*.svc.spcs.internal`, or disable it for this private endpoint |
| `/mcp` fails the readiness probe | Stage 1 `/healthz` test | Probe `/healthz` instead |
| amd64 emulation on Apple Silicon is slow or breaks a dependency | Stage 3 | Accept slower builds; pin wheels that publish amd64 builds |
| Short DNS name `mcp-server` does not resolve | Stage 5 probe | Use the full `dns_name` from `DESCRIBE SERVICE` |
| Stateful MCP sessions break when the server scales past one instance | Designed out with `stateless_http=True` | Keep `MAX_INSTANCES=1` |
| Ingress drops connections idle for 90s | Stage 6 browser soak | The UI already polls every 2s |
| Ingress may refuse a session whose primary role is ACCOUNTADMIN. I have not verified this in this account | Stage 6 browser and PAT tests | Sign in with `MCP_DEMO_ROLE` as the default role, or use a PAT restricted to `MCP_DEMO_ROLE` |
| SDK APIs have moved since my training data | Stages 1 and 2 | Check the current SDK docs and pin versions at scaffold time |

## Cost and cleanup

The pool is created suspended and only runs one XS node while services are up. `suspend.sql` stops all billing for the demo without losing anything; `99_teardown.sql` removes it entirely. The probe job exits when done and costs only the seconds it runs.

## Possible next stages (not in this plan)

Separate owner roles for client and server with a service-role grant, a second tool to show discovery picking it up, and server-sent events for the log feed.
