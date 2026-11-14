"""Shared test doubles."""

from collections.abc import Sequence
from typing import Any

from mcp_server.snowflake import QueryResult


class FakeRunner:
    """Records statements and returns canned rows, or raises a given error."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None):
        self.rows = rows or []
        self.error = error
        self.calls: list[tuple[str, list[Any], int]] = []

    async def run(self, sql: str, params: Sequence[Any] = (), timeout_s: int = 60) -> QueryResult:
        self.calls.append((sql, list(params), timeout_s))
        if self.error:
            raise self.error
        return QueryResult(rows=self.rows, query_id="qid-fake", elapsed_ms=1.0)
