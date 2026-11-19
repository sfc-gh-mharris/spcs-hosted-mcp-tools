"""Cortex Code worker tool (pattern B4): coco_task sends a prompt to the COCO_WORKER service.

The worker runs the cortex CLI through the Cortex Agent SDK in its own container and pool, as its
own service user under MCP_DEMO_ROLE. This server only forwards the prompt over the SPCS internal
network and shapes the reply. Registered on the private toolset only.
"""

import logging
import os
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

logger = logging.getLogger("mcp_server.worker")

DEFAULT_WORKER_URL = "http://coco-worker:8000"
MAX_PROMPT_CHARS = 8000
# The worker caps a run at COCO_MAX_SECONDS (300 by default); allow for startup on top.
WORKER_TIMEOUT_S = 420


class CocoTaskResult(BaseModel):
    answer: str
    turns: int | None
    duration_ms: int | None
    model: str | None
    tool_uses: list[str]
    denials: list[dict[str, str]]
    usage: dict[str, Any] | None


class WorkerClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or os.environ.get("COCO_WORKER_URL", DEFAULT_WORKER_URL)).rstrip("/")
        self._transport = transport

    async def run(self, prompt: str, max_turns: int) -> dict[str, Any]:
        timeout = httpx.Timeout(WORKER_TIMEOUT_S, connect=10)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                response = await client.post(f"{self.base_url}/run", json={"prompt": prompt, "max_turns": max_turns})
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not reach COCO_WORKER at {self.base_url}: {type(exc).__name__}: {exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:300]}
        if response.status_code == 429:
            raise ToolError(f"COCO_WORKER is busy: {body.get('error', 'try again shortly')}")
        if response.status_code != 200:
            raise ToolError(f"COCO_WORKER returned HTTP {response.status_code}: {body.get('error')}")
        return body


def register_worker_tools(mcp: MCPServer, worker: WorkerClient) -> None:
    async def coco_task(
        prompt: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT_CHARS, description="Task for Cortex Code")],
        max_turns: Annotated[int, Field(ge=1, le=12, description="Cap on agent turns")] = 6,
    ) -> CocoTaskResult:
        """Run a read-only Cortex Code (CLI) task in the COCO_WORKER service via the Cortex Agent SDK."""
        body = await worker.run(prompt, max_turns)
        if not body.get("ok"):
            raise ToolError(f"Cortex Code run failed ({body.get('subtype')}): {body.get('error') or body.get('answer')}")
        logger.info("tool=coco_task turns=%s tools=%d denials=%d ms=%s", body.get("turns"),
                    len(body.get("tool_uses") or []), len(body.get("denials") or []), body.get("duration_ms"))
        return CocoTaskResult(
            answer=body.get("answer") or "",
            turns=body.get("turns"),
            duration_ms=body.get("duration_ms"),
            model=body.get("model"),
            tool_uses=[t.get("name", "?") for t in body.get("tool_uses") or []],
            denials=body.get("denials") or [],
            usage=body.get("usage"),
        )

    mcp.add_tool(coco_task)
