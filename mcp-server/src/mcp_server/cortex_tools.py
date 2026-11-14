"""Cortex AI SQL function tools (pattern B1): AI_COMPLETE, AI_CLASSIFY, AI_SENTIMENT.

Every value is a bind variable, so prompts never become SQL. Limits live in the input schema
(model allow-list, prompt length, category count), so bad calls fail before any credits are
spent. These tools are registered on the private toolset only.
"""

import json
import logging
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from mcp_server.snowflake import QueryRunner

logger = logging.getLogger("mcp_server.cortex")

# Chosen in Stage 0: all three answered as MCP_DEMO_ROLE in AWS us-east-1 (cross-region on).
MODELS = ("claude-haiku-4-5", "llama3.3-70b", "claude-sonnet-5")
DEFAULT_MODEL = MODELS[0]
MAX_PROMPT_CHARS = 8000
MAX_TEXT_CHARS = 8000

Model = Literal["claude-haiku-4-5", "llama3.3-70b", "claude-sonnet-5"]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CompleteResult(BaseModel):
    text: str
    model: str
    usage: Usage
    query_id: str


class ClassifyResult(BaseModel):
    label: str
    query_id: str


class SentimentResult(BaseModel):
    sentiment: str
    query_id: str


def _parse(value: Any, query_id: str) -> dict[str, Any]:
    """AI functions come back as JSON text through the connector; NULL means Cortex failed the row."""
    if value is None:
        raise ToolError(f"Cortex returned no result (query_id {query_id})")
    return json.loads(value) if isinstance(value, str) else value


def register_cortex_tools(mcp: MCPServer, runner: QueryRunner) -> None:
    async def cortex_complete(
        prompt: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT_CHARS, description="The prompt to send")],
        model: Annotated[Model, Field(description="Allow-listed Cortex model")] = DEFAULT_MODEL,
        max_tokens: Annotated[int, Field(ge=1, le=4096, description="Cap on generated tokens")] = 1024,
    ) -> CompleteResult:
        """Generate text with a Cortex LLM (AI_COMPLETE). Returns the text and token usage."""
        res = await runner.run(
            "SELECT AI_COMPLETE(model => ?, prompt => ?, model_parameters => PARSE_JSON(?), show_details => TRUE) AS R",
            [model, prompt, json.dumps({"max_tokens": max_tokens, "temperature": 0})],
            timeout_s=120,
        )
        data = _parse(res.rows[0]["R"], res.query_id)
        usage = Usage(**data.get("usage", {}))
        logger.info("tool=cortex_complete model=%s tokens=%s query_id=%s ms=%s",
                    model, usage.total_tokens, res.query_id, res.elapsed_ms)
        return CompleteResult(text=data["choices"][0]["messages"], model=data.get("model", model), usage=usage,
                              query_id=res.query_id)

    async def cortex_classify(
        text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS, description="Text to classify")],
        categories: Annotated[list[str], Field(min_length=2, max_length=20, description="2 to 20 distinct labels")],
    ) -> ClassifyResult:
        """Pick the best-fitting label for a piece of text (AI_CLASSIFY)."""
        if len(set(categories)) != len(categories):
            raise ToolError("categories must be distinct")
        # Two-argument form only: binding the optional config object makes Snowflake resolve the
        # return_error_details overload, which requires a constant (error 001015).
        res = await runner.run("SELECT AI_CLASSIFY(?, PARSE_JSON(?)::ARRAY) AS R", [text, json.dumps(categories)],
                               timeout_s=60)
        labels = _parse(res.rows[0]["R"], res.query_id).get("labels") or []
        if not labels:
            raise ToolError(f"Cortex returned no label (query_id {res.query_id})")
        logger.info("tool=cortex_classify label=%s query_id=%s ms=%s", labels[0], res.query_id, res.elapsed_ms)
        return ClassifyResult(label=labels[0], query_id=res.query_id)

    async def cortex_sentiment(
        text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS, description="Text to score")],
    ) -> SentimentResult:
        """Overall sentiment of a piece of text: positive, negative, neutral, mixed, or unknown (AI_SENTIMENT)."""
        res = await runner.run("SELECT AI_SENTIMENT(?) AS R", [text], timeout_s=60)
        categories = _parse(res.rows[0]["R"], res.query_id).get("categories") or []
        overall = next((c["sentiment"] for c in categories if c.get("name") == "overall"), None)
        if overall is None:
            raise ToolError(f"Cortex returned no overall sentiment (query_id {res.query_id})")
        logger.info("tool=cortex_sentiment sentiment=%s query_id=%s ms=%s", overall, res.query_id, res.elapsed_ms)
        return SentimentResult(sentiment=overall, query_id=res.query_id)

    for fn in (cortex_complete, cortex_classify, cortex_sentiment):
        mcp.add_tool(fn)
