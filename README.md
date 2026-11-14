# MCP servers in Snowpark Container Services, calling and called by Cortex

An MCP server and an MCP client running as Snowpark Container Services (SPCS), wired to Snowflake Cortex in both directions:

- **Snowflake calls our MCP server.** CoCo (Cortex Code) and Cortex Agents call the server's public toolset through SPCS ingress. This is the shape of a customer demo where an agent calls a customer-run MCP server.
- **Our MCP server calls Cortex.** Tools on the private toolset call AI SQL functions, a Cortex Agent, a managed coding agent, and a self-hosted Cortex Code CLI, all through SQL with the container's session token. Nothing leaves Snowflake.

**[PATTERNS.md](PATTERNS.md)** is the reusable part: each pattern with exact DDL, grants, auth, limits, cost, and what was proven.

```
Browser --ingress--> MCP_CLIENT (monitor UI) --private :8000, all tools--> MCP_SERVER
CoCo ------------ingress, Snowflake token---> public :8001, consumer tools  MCP_SERVER
Cortex Agent --CUSTOM MCP SERVER, ingress---> public :8001                  MCP_SERVER
MCP_SERVER --SQL (session token)--> AI_COMPLETE / AI_CLASSIFY / AI_SENTIMENT
                                    DATA_AGENT_RUN (agent calls back into public add)
                                    AGENT_RUN with code_toolset_all
MCP_SERVER --private HTTP--> COCO_WORKER --cortex CLI via Cortex Agent SDK--> Snowflake
```

## What is here

| Path | Contents |
|---|---|
| `mcp-server/` | Python MCP server (`mcp` SDK 2.3): private and public toolsets, an inbound call log, `add`, `snowflake_whoami`, Cortex tools, `ask_agent`, `ask_coding_agent`, `coco_task`, and a `probe` CLI that checks any tool |
| `mcp-client/` | Node MCP client and monitor: forms built from each tool's schema, background jobs, an Inbound (Snowflake) tab, and a traffic generator that only calls `add` |
| `coco-worker/` | Starlette service running a pinned `cortex` CLI through `snowflake-cortex-agent-sdk`, read-only, one run at a time |
| `compose.yaml` | All images on one Docker network with SPCS hostnames (`--profile worker` adds the worker) |
| `spcs/` | Setup SQL (`00` to `03`), service specs, the agent spec's grants, suspend, resume, teardown, cost |
| `cortex_project/` | The `MCP_DEMO_AGENT` spec, managed with `cortex agent-studio` |
| `scripts/` | Build and push, rolling deploy, worker creation, local and SPCS smoke tests, SPCS probe jobs |
| `.snowflake/cortex/plans/` | The staged, test-gated plans this was built from |

## Tools

| Tool | Toolset | What it does |
|---|---|---|
| `add` | public and private | Sums two numbers; the stand-in for consumer tools |
| `snowflake_whoami` | private | User, role, and warehouse the server's SQL runs as |
| `cortex_complete`, `cortex_classify`, `cortex_sentiment` | private | `AI_COMPLETE` (model allow-list), `AI_CLASSIFY`, `AI_SENTIMENT` |
| `ask_agent` | private | `DATA_AGENT_RUN` on `MCP_DEMO_AGENT`, whose only tool is the public `add` |
| `ask_coding_agent` | private | `AGENT_RUN` with an inline `code_toolset_all` spec (managed sandbox) |
| `coco_task` | private | Sends a prompt to `COCO_WORKER` (Cortex Code CLI) |

## Prerequisites

- Docker with `linux/amd64` builds (SPCS runs amd64 only; Apple Silicon builds under emulation)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/), Node 22+
- Snowflake CLI with a connection to an account that has SPCS and Cortex. Every script takes the connection from `SNOW_CONNECTION`:

```bash
export SNOW_CONNECTION=<your snow CLI connection name>
```

- For the CoCo checks, the Cortex Code CLI (`cortex`).

## Run the tests locally

```bash
cd mcp-server && uv run pytest              # unit and HTTP tests; live Snowflake tests skip without SNOW_CONNECTION
SNOW_CONNECTION=<conn> uv run pytest -m snowflake          # live: whoami and each AI function as MCP_DEMO_ROLE
SNOW_CONNECTION=<conn> LIVE_AGENT=1 uv run pytest -m snowflake -k ask_agent   # costs agent tokens
cd mcp-client && npm install && npm test    # against an in-process fake MCP server
cd coco-worker && uv run pytest             # worker with a fake SDK query()

bash scripts/smoke_local.sh                 # images on Compose; WITH_WORKER=1 adds the worker
```

## Deploy to SPCS

1. Foundation, as ACCOUNTADMIN: role, database, image repository, compute pool. Then the warehouse and Cortex grants.

   ```bash
   snow sql -c "$SNOW_CONNECTION" -f spcs/00_setup.sql
   snow sql -c "$SNOW_CONNECTION" -f spcs/01_cortex_setup.sql
   ```

2. Build, push, and create the server and client (specs in `spcs/`), then roll updates with `deploy.sh`. `deploy.sh server` also fills the public ingress hostname into the server's allow-list. Deploy it a second time after `SHOW ENDPOINTS` lists the `mcp-public` URL.

   ```bash
   bash scripts/build_push.sh v1
   # CREATE SERVICE MCP_SPCS_DEMO.APP.MCP_SERVER / MCP_CLIENT ... FROM SPECIFICATION $$ <spec> $$
   bash scripts/deploy.sh server v1
   python3 scripts/probe_spcs.py --tool snowflake_whoami --expect role=MCP_DEMO_ROLE
   ```

3. Let Snowflake call the server: the custom MCP server object, the agent, and a least-privilege consumer role.

   ```bash
   cortex agent-studio agent-deploy --file-path cortex_project/spcs/MCP_DEMO_AGENT.agent.yaml --fqn MCP_SPCS_DEMO.APP.MCP_DEMO_AGENT
   snow sql -c "$SNOW_CONNECTION" -f spcs/02_agent_mcp.sql   # also moves agent ownership to MCP_DEMO_ROLE (see PATTERNS.md)
   ```

4. The Cortex Code worker, on its own pool:

   ```bash
   snow sql -c "$SNOW_CONNECTION" -f spcs/03_coco_pool.sql
   bash scripts/build_push.sh w1 coco-worker
   bash scripts/create_worker.sh
   ```

5. Check everything through the monitor's ingress with a PAT (from `SNOWFLAKE_PAT` or the `token` field of your connection; never printed):

   ```bash
   python3 scripts/smoke_spcs.py --cortex           # AI functions as background jobs
   python3 scripts/smoke_spcs.py --agents           # plus ask_agent, ask_coding_agent, coco_task
   ```

Open the monitor's ingress URL in a browser and sign in with your Snowflake user. The Inbound (Snowflake) tab shows what CoCo and Cortex Agents called.

## Operate

```bash
bash scripts/deploy.sh <server|client|worker> <tag>                  # rolling update; ingress URLs are kept
snow sql -c "$SNOW_CONNECTION" -f spcs/suspend.sql                   # stop billing (services, pools, warehouse)
snow sql -c "$SNOW_CONNECTION" -f spcs/resume.sql                    # bring it back
snow sql -c "$SNOW_CONNECTION" -f spcs/cost.sql                      # spend by pattern
snow sql -c "$SNOW_CONNECTION" -f spcs/99_teardown.sql               # remove everything
```

## Things we learned building it

Step 2 findings (Cortex in both directions) are in [PATTERNS.md](PATTERNS.md). From step 1:

- **Auto-resume only reacts to ingress.** A suspended service with `AUTO_RESUME = TRUE` wakes when its public endpoint gets a request, but not when another service calls it. With the monitor tab open, a plain `SUSPEND` woke the client and the pool within 20 seconds while the server stayed down. `spcs/suspend.sql` turns `AUTO_RESUME` off first; `spcs/resume.sql` restores it.
- **MCP Python SDK 2.x renamed FastMCP to `MCPServer`** (`from mcp.server.mcpserver import MCPServer`), and host and port move to run time. Its DNS-rebinding protection switches on only when bound to localhost, so the server passes explicit allow-lists, and tests prove an unknown `Host` gets 421.
- **Protocol versions differ by SDK and both work.** The Python client negotiates `2026-07-28`; the Node SDK 1.32 uses the `2025-11-25` initialize handshake.
- **`/mcp` cannot be the readiness probe.** It does not answer a plain GET with 200, so services expose `/healthz`.
- **Same-schema services resolve by short name.** `MCP_SERVER` is reachable as `mcp-server:8000`.
- **A default role of ACCOUNTADMIN did not block ingress** for either PAT or browser sign-in in our account.
