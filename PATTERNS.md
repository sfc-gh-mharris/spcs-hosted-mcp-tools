# Patterns: MCP servers in SPCS and Snowflake Cortex

Reusable patterns proven on branch `feature/cortex-tools`. Each section says what works, the exact
objects and grants, how auth works, limits, cost, and the evidence from this repo. Everything runs
inside Snowflake: no egress, no external access integration, no REST round trips.

| | Pattern | Direction | Status here |
|---|---|---|---|
| A1 | CoCo as an MCP client | Snowflake calls us | Proven |
| A2 | Cortex Agent through a `CUSTOM MCP SERVER` | Snowflake calls us | Proven, standalone (not a Native App) |
| A3 | The same agent in Snowflake CoWork | Snowflake calls us | Follows from A2, not tested |
| A4 | Production analogue: `EXTERNAL MCP SERVER` for a customer-run server | Snowflake calls them | Documented only |
| B1 | AI SQL functions | We call Cortex | Proven |
| B2 | Cortex Agent via `DATA_AGENT_RUN` | We call Cortex | Proven, including the round trip through A2 |
| B3 | Managed coding agent via `AGENT_RUN` + `code_toolset_all` | We call Cortex | Proven from SPCS |
| B4 | Self-hosted Cortex Code CLI (`COCO_WORKER`) | We call Cortex | Proven from SPCS |

Figures below are from this demo account (AWS us-east-1, cross-region inference on) on 2026-11-13.

## Foundations used by every pattern

**Two endpoints, two toolsets.** `MCP_SERVER` runs two MCP apps in one process
(`mcp-server/src/mcp_server/__main__.py`):

- `mcp` on port 8000, private: every tool, for services in the schema (`http://mcp-server:8000/mcp`).
- `mcp-public` on port 8001, public: only the tools Snowflake consumers should see (just `add` now;
  the Factory tools in step 3).

The split stops an agent pointed at the public endpoint from calling `ask_agent` or `coco_task`
and recursing into Cortex through us. One recorder middleware logs every call on both, with the
caller from `Sf-Context-Current-User`; the private `GET /calls` serves it to the monitor.

**Host header allow-list.** The MCP SDK rejects unknown `Host` headers (421). SPCS ingress forwards
the public ingress hostname itself, so it must be in `MCP_PUBLIC_ALLOWED_HOSTS`. It is
account-specific and only known after the endpoint is provisioned, so `scripts/deploy.sh` reads it
from `SHOW ENDPOINTS` and substitutes `__PUBLIC_INGRESS_HOST__` in the spec.

**SQL from a container** (`mcp-server/src/mcp_server/snowflake.py`). In SPCS, Snowflake mounts an
OAuth token at `/snowflake/session/token` and sets `SNOWFLAKE_HOST` and `SNOWFLAKE_ACCOUNT`:

```python
snowflake.connector.connect(host=env["SNOWFLAKE_HOST"], account=env["SNOWFLAKE_ACCOUNT"],
                            authenticator="oauth", token=open(token_path).read().strip(),
                            paramstyle="qmark", session_parameters={"QUERY_TAG": "spcs-mcp-demo"})
```

- Re-read the token on every connect; Snowflake rotates it.
- Sessions run as the service user (named after the service, for example `MCP_SERVER`) under the
  service owner role. The warehouse comes from the service's `QUERY_WAREHOUSE`, so code needs none.
- `paramstyle="qmark"` gives server-side binds: prompts and arguments are never spliced into SQL.
- Locally, use a named connection, then `USE SECONDARY ROLES NONE` with the same role and
  warehouse. Without that, a user with `DEFAULT_SECONDARY_ROLES = ALL` passes tests on grants the
  service user does not have.

**Grants for outbound Cortex** (`spcs/01_cortex_setup.sql`): a warehouse owned by the service role,
`GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MCP_DEMO_ROLE`, and
`ALTER SERVICE ... SET QUERY_WAREHOUSE`. Many accounts already grant `CORTEX_USER` and
`USE AI FUNCTIONS` to PUBLIC; grant explicitly anyway so the recipe survives a locked-down account.

**Long calls.** SPCS ingress drops idle connections after 90 s, Node's fetch gives up after 300 s
without headers, and the MCP SDK's default request timeout is 60 s. The monitor runs every tool
as a background job (`POST /api/jobs` returns 202) and polls for the result, with per-tool timeouts
up to 15 minutes and an undici dispatcher that raises Node's limits on the client-to-server hop.

## A1. CoCo as an MCP client

CoCo connects straight to the public endpoint's ingress URL with a Snowflake token.

```bash
# Persistent (writes ~/.snowflake/cortex/mcp.json):
cortex mcp add spcs-demo https://<public-ingress>/mcp --type http --snowflake-connection <conn>

# Headless, without touching mcp.json:
cortex -p "Use the add tool to compute 19.5 + 22.5. Reply with only the number." -c <conn> \
  --only-explicit-mcp-servers --mcp-wait \
  --mcp-config '{"mcpServers":{"spcs-demo":{"type":"http","url":"https://<public-ingress>/mcp","snowflake_connection":"<conn>"}}}' \
  --allowed-tools "mcp__spcs-demo__add" --output-format stream-json
```

- **Grants:** the user's role needs endpoint access, the `mcp_consumer` service role (see A2).
- **Identity:** ingress adds `Sf-Context-Current-User`; the inbound log showed the real user.
- **Evidence:** CLI 1.2.44 found `mcp__spcs-demo__add`, called it with `{a: 19.5, b: 22.5}` and
  answered 42. The server logged `endpoint=public tool=add caller=<user>`.
- **Gotcha:** the config key is `snowflake_connection`, the same one `cortex mcp add --snowflake-connection` writes.

## A2. Cortex Agent through a CUSTOM MCP SERVER

Register the public endpoint as an MCP server object, then reference it from an agent
(`spcs/02_agent_mcp.sql`, `cortex_project/spcs/MCP_DEMO_AGENT.agent.yaml`):

```sql
CREATE CUSTOM MCP SERVER IF NOT EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC
  SERVICE = MCP_SPCS_DEMO.APP.MCP_SERVER
  ENDPOINT = "mcp-public"
  PATH = '/mcp';
DESC CUSTOM MCP SERVER MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC;   -- url = the ingress host + /mcp
```

```yaml
models: {orchestration: auto}
orchestration: {budget: {seconds: 120, tokens: 20000}}
instructions:
  orchestration: 'For any addition, call the add tool from the MCP server instead of computing the sum yourself.'
mcp_servers:
  - server_spec: {name: "MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC"}
```

- **Works standalone.** The docs show `CREATE CUSTOM MCP SERVER` only inside Native Apps; it
  compiles and runs in a plain account. So the plan's go/no-go was a go, and the Native App,
  service-function, and CoCo-only fallbacks were not needed.
- **The endpoint must be public.** Snowflake calls the ingress URL, not the internal DNS name.
- **Least-privilege consumer**, six grants, verified as `MCP_DEMO_CONSUMER_ROLE` with secondary roles off:

  ```sql
  GRANT USAGE ON DATABASE MCP_SPCS_DEMO TO ROLE MCP_DEMO_CONSUMER_ROLE;
  GRANT USAGE ON SCHEMA MCP_SPCS_DEMO.APP TO ROLE MCP_DEMO_CONSUMER_ROLE;
  GRANT USAGE ON AGENT MCP_SPCS_DEMO.APP.MCP_DEMO_AGENT TO ROLE MCP_DEMO_CONSUMER_ROLE;
  GRANT USAGE ON CUSTOM MCP SERVER MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC TO ROLE MCP_DEMO_CONSUMER_ROLE;
  GRANT SERVICE ROLE MCP_SPCS_DEMO.APP.MCP_SERVER!MCP_CONSUMER TO ROLE MCP_DEMO_CONSUMER_ROLE;
  GRANT USAGE ON WAREHOUSE MCP_DEMO_WH TO ROLE MCP_DEMO_CONSUMER_ROLE;   -- DATA_AGENT_RUN is SQL
  ```

  `mcp_consumer` is a service role in the spec that covers only `mcp-public`. Use it instead of
  `ALL_ENDPOINTS_USAGE`, which would also open the private port and its call log.
- **Diagnosing access:** without the endpoint grant the agent still answers, but the response has
  warning `399540`: "Custom MCP server '...' is unavailable and will be skipped". Check
  `warnings[]` on every agent response.
- **What the agent sees:** tools are named `<server object>_<tool>` (`mcp_server_public_add`),
  and the agent adds a `description` argument to calls. Tools must tolerate extra arguments.
- **Identity:** `Sf-Context-Current-User` is whoever ran the agent: the person for
  `DATA_AGENT_RUN` from a worksheet, and `MCP_SERVER` when our own service ran it (B2).
- **Creating the agent:** `cortex agent-studio agent-deploy` creates it as the connection's role.
  Run `GRANT OWNERSHIP ON AGENT ... TO ROLE MCP_DEMO_ROLE COPY CURRENT GRANTS` afterwards.

## A3. Snowflake CoWork

An agent with `USAGE` granted appears in CoWork, so the A2 agent should work there unchanged.
Not tested on this branch.

## A4. Production analogue for a customer-run MCP server

For the real Factory MCP server outside Snowflake, the documented path is an API integration with
`API_PROVIDER = EXTERNAL_MCP` (OAuth) plus `CREATE EXTERNAL MCP SERVER ... URL = ...`, referenced
from the agent's `mcp_servers` the same way as A2. CoCo can point straight at the URL as in A1.
The SPCS mock cannot prove this path, because it is reached through Snowflake auth, not OAuth.
Documented, not tested.

## B1. AI SQL functions

`mcp-server/src/mcp_server/cortex_tools.py`: `cortex_complete`, `cortex_classify`, `cortex_sentiment`.

```sql
SELECT AI_COMPLETE(model => ?, prompt => ?, model_parameters => PARSE_JSON(?), show_details => TRUE);
SELECT AI_CLASSIFY(?, PARSE_JSON(?)::ARRAY);
SELECT AI_SENTIMENT(?);
```

- All arguments bind, including the model and an array built with `PARSE_JSON(?)::ARRAY`.
- `show_details => TRUE` returns token usage alongside the text.
- Results come back through the connector as JSON text; parse them. A NULL means Cortex failed the row.
- **Gotcha:** `AI_CLASSIFY(?, ?, PARSE_JSON(?))` fails with 001015. A bound third argument
  resolves to the `return_error_details` overload, which needs a constant. Use the two-argument form.
- **Guardrails in the schema:** the model allow-list (`claude-haiku-4-5` default, `llama3.3-70b`,
  `claude-sonnet-5`), prompt length, and category count are in the input schema, so bad calls fail
  before any credits are spent. The monitor renders the allow-list as a dropdown.
- **Cost:** about 0.0002 to 0.0003 credits per call here. The warehouse is the bigger cost: each
  resume bills at least 60 s, which came to 0.4 credits for a handful of calls. For bursty tool
  traffic, share a warehouse that is already warm.

## B2. Cortex Agent via DATA_AGENT_RUN

`mcp-server/src/mcp_server/agent_tools.py`, `ask_agent`:

```sql
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?);   -- agent FQN, request body JSON
```

- The agent name and body both bind. Keep an allow-list of agents in the tool schema.
- It returns one aggregated JSON value (no streaming), synchronously, with a 15-minute limit. Parse
  `content[]` for `text`, `tool_use`, and `tool_result` (the outcome), and also read `warnings[]`
  and `metadata.usage`.
- **The round trip:** the demo agent's only tool is our public `add`. So one call goes monitor →
  private `ask_agent` → Cortex Agent → public `add` → answer, and the inbound log shows the nested
  call inside the outer one. No recursion is possible: the public toolset has no `ask_agent`.
- **Cost:** `orchestration: auto` chose `claude-opus-5-5`, using about 37k input tokens (mostly
  cache) for one addition. That is 0.015 to 0.05 credits per run, depending on cache hits. Pin a
  smaller model in the agent spec when cost matters.
- **Usage history:** `CORTEX_AGENT_USAGE_HISTORY` records each run with the agent name and the
  calling user (`MCP_SERVER` for service-initiated runs).
- **Namespace note:** AI functions use the `AI_*` forms. `DATA_AGENT_RUN` and `AGENT_RUN` exist
  only under `SNOWFLAKE.CORTEX` and are current, not deprecated.

## B3. Managed coding agent via AGENT_RUN

`ask_coding_agent` sends an inline spec, so there is no agent object and nothing to host:

```json
{
  "models": {"orchestration": "claude-sonnet-5"},
  "thinking_effort": "low",
  "orchestration": {"budget": {"seconds": 240}},
  "instructions": {"system": "Work read-only: run only SELECT and SHOW statements ..."},
  "messages": [{"role": "user", "content": [{"type": "text", "text": "<task>"}]}],
  "tools": [{"tool_spec": {"type": "code_toolset_all", "name": "code_toolset_all"}}],
  "tool_resources": {"code_toolset_all": {"permission_policy": {"type": "always_allow"}}}
}
```

- `SELECT SNOWFLAKE.CORTEX.AGENT_RUN(?)` returns one JSON value. The sandbox provides bash, files,
  web search, skills, and `snowflake_sql_execute` (SELECT and SHOW only).
- **`always_allow` is required** for unattended calls. Under the default `always_ask`, the run
  stops at the first state-changing tool, because SQL cannot answer the approval prompt. The real
  limit is the role's grants; here `MCP_DEMO_ROLE` owns only the demo database.
- **Works from SPCS.** The docs say sandbox tools are removed in owner's-rights contexts. A call from
  an SPCS service user's session kept the sandbox: the probe job's answer matched `SHOW`.
- **Cost:** about 165k input tokens (0.05 to 0.15 credits) per run, mostly the sandbox's system
  prompt, even for a trivial question. Inline runs have an empty agent name in
  `CORTEX_AGENT_USAGE_HISTORY`, so attribute them by user.
- **Alternative:** a Snowflake-managed `CREATE MCP SERVER` with a `CODING_AGENT` tool exposes the
  same agent to MCP clients without our server.

## B4. Self-hosted Cortex Code CLI (COCO_WORKER)

A separate service on its own pool runs the `cortex` CLI through `snowflake-cortex-agent-sdk`
(`cortex_agent_sdk.cortexcode.query`). `MCP_SERVER`'s `coco_task` POSTs to
`http://coco-worker:8000/run`.

- **Why a separate service:** the SDK pins `mcp<2` and `snowflake-connector-python<5`, which
  conflict with the server's versions. The CLI is a 156 MB binary and the image is about 1.1 GB.
  It also keeps a long CLI run from starving the server.
- **Pinned CLI:** the install script only installs the latest build. The Dockerfile replays it for one
  version: read `manifest.json` for that version, download the linux/amd64 tarball, check its
  SHA-256, and set `"autoUpdate": false` in `~/.snowflake/cortex/settings.json`. Versions carry a
  build suffix (`1.2.45+061229.2a20c0482251`, `+` encoded as `%2B` in the URL).
- **Auth with the session token, no PAT:** `sessionTokenConfig.mountConnectionConfig: true` makes
  SPCS write a `[default]` OAuth connection (`token_file_path`, `host`, `account`) to
  `/snowflake/home/connections.toml` and set `SNOWFLAKE_HOME` to that directory.
  - **Gotcha:** that directory is read-only, and the CLI keeps its state under
    `SNOWFLAKE_HOME/cortex`, so it exits with `EACCES ... mkdir '/snowflake/home/cortex/conversations'`.
  - **Fix** (`coco-worker/src/coco_worker/cli_home.py`): copy `connections.toml` to a writable
    `~/.snowflake` and set `SNOWFLAKE_HOME` there, for the CLI process only. The copy holds the
    token file path, not the token, so rotation still works.
  - The CLI then runs as user `COCO_WORKER` under `MCP_DEMO_ROLE`, on the service's `QUERY_WAREHOUSE`.
- **Keeping it read-only:**
  - `disallowed_tools` removes interactive and side-effect tools. Without that, the agent tried
    `ask_user_question` and stalled.
  - A `can_use_tool` callback allows only one read-only SQL statement per call.
  - The callback receives tool `SQL` with `{action, resource}`, not the model-facing `sql_execute`
    with `sql`.
  - `ResultMessage.permission_denials` stayed empty even when the callback denied, so the worker
    records denials itself.
- **Bounds:** a turn cap, a wall-clock cap that cancels the CLI through `aclosing()`, one run at a
  time (429 when busy), a pinned model, and low effort.
- **Debugging:** the SDK drops CLI stderr unless you pass a `stderr` callback; failures otherwise
  show only "exit code 1". `/selfcheck?deep=1` runs a tiny task and returns the CLI's error.
- **Cost:** about 80k to 135k input tokens per run, mostly cache reads, recorded in
  `CORTEX_CODE_CLI_USAGE_HISTORY` under user `COCO_WORKER`. That is about 0.03 credits per run,
  plus the pool's compute.
- **Related:** Snowflake also publishes `cortex-code-agent-sdk`, a CoCo-specific SDK with a similar
  `query()`. This repo uses `snowflake-cortex-agent-sdk`.

## Choosing between B2, B3 and B4

| | B2 `DATA_AGENT_RUN` | B3 `AGENT_RUN` + `code_toolset_all` | B4 COCO_WORKER |
|---|---|---|---|
| Hosting | none (agent object) | none (inline spec) | a service, pool, and 1.1 GB image |
| Tools | the agent's tools (MCP, Analyst, Search, procedures) | Snowflake sandbox: bash, files, read-only SQL, skills | the CLI's tools, filtered by you |
| Control | agent spec | permission policy (all or nothing) | per-call permission callback, custom deny list |
| Typical tokens | about 37k (Opus via auto) | about 165k | about 80k to 135k |
| Use when | the agent already exists or needs MCP tools | you want a coding sandbox with no infrastructure | you need fine-grained control or local files and MCP config |

## Operations

- `spcs/suspend.sql` and `spcs/resume.sql` cover all three services, both pools, and the warehouse.
  Auto-resume is turned off first, because a monitor tab or a Snowflake call through ingress would
  wake a service within seconds. Service-to-service calls never auto-resume anything.
- `spcs/cost.sql` breaks spend down by pattern: AI functions by query tag, agents by name and user,
  the CLI by worker user, and the pools and warehouse.
- `scripts/smoke_spcs.py --cortex --agents` runs every tool as a background job through the
  monitor's ingress.

## Not done

- **Caller's rights** (`executeAsCaller` plus `Sf-Context-Current-User-Token`), so outbound Cortex
  calls would run as the end user rather than the service role. All outbound calls here run as
  `MCP_DEMO_ROLE`.
- **REST paths** (`agent:run`, chat completions, Search, Analyst over HTTP): out of scope by decision.
- **A4 against a real external server**, and **A3** in the CoWork UI.
