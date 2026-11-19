"""Cortex Agent tools: ask_agent (pattern B2) and ask_coding_agent (pattern B3).

Both are SQL functions, so they use the same session token and grants as the AI function
tools; nothing leaves Snowflake. Each returns one aggregated JSON response (no stream),
synchronously, with a 15 minute limit.

- ask_agent runs DATA_AGENT_RUN on an allow-listed agent object. The demo agent's only tool is
  this server's public `add`, so one call exercises both directions: us -> Cortex Agent -> us.
- ask_coding_agent runs AGENT_RUN with an inline code_toolset_all spec: a managed Cortex Code
  sandbox (bash, files, read-only SQL) with no agent object and nothing to host.

Registered on the private toolset only, so an agent pointed at the public endpoint cannot
call back into an agent through us.
"""

import json
import logging
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from mcp_server.snowflake import QueryRunner

logger = logging.getLogger("mcp_server.agent")

AGENTS = ("MCP_SPCS_DEMO.APP.MCP_DEMO_AGENT",)
DEFAULT_AGENT = AGENTS[0]
AGENT_TIMEOUT_S = 900  # DATA_AGENT_RUN's synchronous limit
MAX_QUESTION_CHARS = 4000

AgentName = Literal["MCP_SPCS_DEMO.APP.MCP_DEMO_AGENT"]

# A pinned model keeps cost predictable; `auto` picked the largest model in testing.
CODING_MODEL = "claude-sonnet-5"
DEFAULT_CODING_SECONDS = 240
MAX_CODING_SECONDS = 600
MAX_TASK_CHARS = 4000
# Prompt-level guidance only. The real limit is MCP_DEMO_ROLE's grants (it owns only the demo
# database), and the sandbox SQL tool itself accepts only SELECT and SHOW.
CODING_INSTRUCTIONS = (
    "Work read-only: run only SELECT and SHOW statements, and only inside the MCP_SPCS_DEMO database. "
    "Do not create, modify, or delete anything. Answer concisely."
)


class ToolUse(BaseModel):
    name: str
    type: str | None = None
    mcp_server: str | None = None
    input: dict[str, Any] = {}
    status: str | None = None


class AgentAnswer(BaseModel):
    answer: str
    status: str | None
    tool_uses: list[ToolUse]
    warnings: list[str]
    model: str | None
    input_tokens: int
    output_tokens: int


class AskAgentResult(AgentAnswer):
    agent: str
    query_id: str


class CodingAgentResult(AgentAnswer):
    query_id: str


def _error_text(err: Any) -> str:
    if isinstance(err, dict):
        return f"{err.get('code', 'unknown')}: {err.get('message', '')}".strip()
    return str(err)


def parse_agent_response(raw: Any) -> AgentAnswer:
    """Turn DATA_AGENT_RUN's JSON into answer text, tool uses with outcomes, warnings, and usage."""
    if raw is None:
        raise ToolError("Cortex Agent returned no result")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ToolError(f"Cortex Agent returned non-JSON output: {str(raw)[:200]}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"Unexpected Cortex Agent response: {str(raw)[:200]}")
    # Errors come back either as {code, message} or as a failed run with an error object.
    if "content" not in data and "code" in data:
        raise ToolError(f"Cortex Agent error {_error_text(data)}")
    if data.get("status") == "failed" or (data.get("error") and not data.get("content")):
        raise ToolError(f"Cortex Agent error {_error_text(data.get('error'))}")

    texts: list[str] = []
    uses: dict[str, ToolUse] = {}
    for part in data.get("content") or []:
        kind = part.get("type")
        if kind == "text" and part.get("text"):
            texts.append(part["text"])
        elif kind == "tool_use":
            use = part.get("tool_use") or {}
            uses[use.get("tool_use_id") or str(len(uses))] = ToolUse(
                name=use.get("name", "?"), type=use.get("type"), mcp_server=use.get("mcp_server_fqn"),
                input=use.get("input") or {},
            )
        elif kind == "tool_result":
            result = part.get("tool_result") or {}
            if (use := uses.get(result.get("tool_use_id"))) is not None:
                use.status = result.get("status")

    input_tokens = output_tokens = 0
    for usage in (data.get("metadata") or {}).get("usage", {}).get("tokens_consumed", []):
        input_tokens += (usage.get("input_tokens") or {}).get("total", 0)
        output_tokens += (usage.get("output_tokens") or {}).get("total", 0)

    return AgentAnswer(
        answer="\n\n".join(texts),
        status=data.get("status"),
        tool_uses=list(uses.values()),
        warnings=[_error_text(w) for w in data.get("warnings") or []],
        model=(data.get("metadata") or {}).get("orchestration_model"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def register_agent_tools(mcp: MCPServer, runner: QueryRunner) -> None:
    async def ask_agent(
        question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION_CHARS, description="Question for the agent")],
        agent: Annotated[AgentName, Field(description="Allow-listed Cortex Agent")] = DEFAULT_AGENT,
    ) -> AskAgentResult:
        """Ask a Cortex Agent (DATA_AGENT_RUN). The demo agent answers by calling this server's public add tool."""
        body = {"messages": [{"role": "user", "content": [{"type": "text", "text": question}]}]}
        res = await runner.run("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", [agent, json.dumps(body)],
                               timeout_s=AGENT_TIMEOUT_S)
        parsed = parse_agent_response(res.rows[0]["R"])
        logger.info("tool=ask_agent agent=%s tools=%s warnings=%d tokens_in=%d query_id=%s ms=%s",
                    agent, [u.name for u in parsed.tool_uses], len(parsed.warnings), parsed.input_tokens,
                    res.query_id, res.elapsed_ms)
        return AskAgentResult(**parsed.model_dump(), agent=agent, query_id=res.query_id)

    async def ask_coding_agent(
        task: Annotated[str, Field(min_length=1, max_length=MAX_TASK_CHARS, description="What the coding agent should do")],
        max_seconds: Annotated[int, Field(ge=30, le=MAX_CODING_SECONDS, description="Agent time budget")] = DEFAULT_CODING_SECONDS,
    ) -> CodingAgentResult:
        """Run a managed Cortex Code agent in a Snowflake sandbox (AGENT_RUN with code_toolset_all). Read-only."""
        body = {
            "models": {"orchestration": CODING_MODEL},
            "thinking_effort": "low",
            "orchestration": {"budget": {"seconds": max_seconds}},
            "instructions": {"system": CODING_INSTRUCTIONS},
            "messages": [{"role": "user", "content": [{"type": "text", "text": task}]}],
            "tools": [{"tool_spec": {"type": "code_toolset_all", "name": "code_toolset_all"}}],
            # Unattended SQL calls cannot answer approval prompts, so without always_allow the run
            # stops at the first state-changing tool call.
            "tool_resources": {"code_toolset_all": {"permission_policy": {"type": "always_allow"}}},
        }
        res = await runner.run("SELECT SNOWFLAKE.CORTEX.AGENT_RUN(?) AS R", [json.dumps(body)],
                               timeout_s=min(max_seconds + 120, AGENT_TIMEOUT_S))
        parsed = parse_agent_response(res.rows[0]["R"])
        logger.info("tool=ask_coding_agent tools=%d warnings=%d tokens_in=%d query_id=%s ms=%s",
                    len(parsed.tool_uses), len(parsed.warnings), parsed.input_tokens, res.query_id, res.elapsed_ms)
        return CodingAgentResult(**parsed.model_dump(), query_id=res.query_id)

    mcp.add_tool(ask_agent)
    mcp.add_tool(ask_coding_agent)
