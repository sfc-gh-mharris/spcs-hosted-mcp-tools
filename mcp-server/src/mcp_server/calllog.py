"""Records every MCP tool call per endpoint, so the monitor can show what Snowflake called.

Wired in as MCP server middleware, so tools need no changes. Snowflake ingress adds the
Sf-Context-Current-User header to public requests; it is recorded as the caller.
"""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("mcp_server.calls")

CALLER_HEADER = "sf-context-current-user"
_TRUNCATED = "...(truncated)"


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + _TRUNCATED
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value]
    return value


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    return result if isinstance(result, dict) else {}


class CallRecorder:
    def __init__(self, capacity: int = 500, max_value_chars: int = 2000):
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._next_id = 1
        self._max_value_chars = max_value_chars

    @property
    def last_id(self) -> int:
        return self._next_id - 1

    def record(self, *, endpoint: str, tool: str | None, args: Any, ok: bool, result: Any, error: str | None,
               latency_ms: float, caller: str | None, protocol: str | None) -> dict[str, Any]:
        entry = {
            "id": self._next_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "tool": tool,
            "args": _truncate(args, self._max_value_chars),
            "ok": ok,
            "result": _truncate(result, self._max_value_chars),
            "error": _truncate(error, self._max_value_chars),
            "latency_ms": latency_ms,
            "caller": caller,
            "protocol": protocol,
        }
        self._next_id += 1
        self._entries.append(entry)
        logger.info("inbound endpoint=%s tool=%s caller=%s ok=%s ms=%.1f", endpoint, tool, caller, ok, latency_ms)
        return entry

    def since(self, entry_id: int = 0) -> list[dict[str, Any]]:
        return [e for e in self._entries if e["id"] > entry_id]

    def middleware(self, endpoint: str):
        async def record_tool_calls(ctx, call_next):
            if ctx.method != "tools/call":
                return await call_next(ctx)
            params = ctx.params or {}
            headers = getattr(ctx.request, "headers", None)
            common = {
                "endpoint": endpoint,
                "tool": params.get("name"),
                "args": params.get("arguments") or {},
                "caller": headers.get(CALLER_HEADER) if headers is not None else None,
                "protocol": ctx.protocol_version,
            }
            start = time.perf_counter()
            try:
                result = await call_next(ctx)
            except Exception as exc:
                self.record(**common, ok=False, result=None, error=f"{type(exc).__name__}: {exc}",
                            latency_ms=round((time.perf_counter() - start) * 1000, 1))
                raise
            data = _as_dict(result)
            is_error = bool(data.get("isError", data.get("is_error", False)))
            text = " ".join(c.get("text", "") for c in data.get("content", []) if isinstance(c, dict))
            structured = data.get("structuredContent", data.get("structured_content"))
            self.record(**common, ok=not is_error, result=None if is_error else structured,
                        error=text if is_error else None,
                        latency_ms=round((time.perf_counter() - start) * 1000, 1))
            return result

        return record_tool_calls
