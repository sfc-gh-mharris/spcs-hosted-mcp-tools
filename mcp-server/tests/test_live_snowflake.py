"""Live checks against Snowflake. Run with SNOW_CONNECTION set, e.g.:

    SNOW_CONNECTION=<your connection> uv run pytest -m snowflake

The server subprocess (conftest) inherits SNOW_CONNECTION, pins MCP_DEMO_ROLE and MCP_DEMO_WH,
and turns secondary roles off, so these see the same grants the SPCS service user has.
"""

import os

import pytest
from mcp import Client

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.snowflake,
    pytest.mark.skipif(not os.environ.get("SNOW_CONNECTION"), reason="set SNOW_CONNECTION for live Snowflake tests"),
]


async def test_whoami_runs_as_demo_role(mcp_url):
    async with Client(mcp_url) as client:
        result = await client.call_tool("snowflake_whoami", {})
    assert not result.is_error, result.content
    data = result.structured_content
    assert data["role"] == "MCP_DEMO_ROLE"
    assert data["warehouse"] == "MCP_DEMO_WH"
    assert data["query_id"]
