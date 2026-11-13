import httpx
import pytest
from mcp import Client

pytestmark = pytest.mark.anyio

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "raw-http-test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def test_healthz_ok(base_url):
    async with httpx.AsyncClient() as http:
        r = await http.get(f"{base_url}/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["instance"]


async def test_initialize_reports_server_name(mcp_url):
    async with Client(mcp_url) as client:
        assert client.server_info.name == "spcs-add-server"


async def test_list_tools_has_add_with_numeric_schema(mcp_url):
    async with Client(mcp_url) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert "add" in tools
    schema = tools["add"].input_schema
    assert schema["properties"]["a"]["type"] == "number"
    assert schema["properties"]["b"]["type"] == "number"
    assert set(schema["required"]) == {"a", "b"}


async def test_call_add_returns_5(mcp_url):
    async with Client(mcp_url) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})
    assert not result.is_error
    assert result.structured_content == {"result": 5}


async def test_call_add_missing_arg_is_error(mcp_url):
    async with Client(mcp_url) as client:
        result = await client.call_tool("add", {"a": 2})
    assert result.is_error


async def test_call_add_non_numeric_is_error(mcp_url):
    async with Client(mcp_url) as client:
        result = await client.call_tool("add", {"a": "x", "b": 1})
    assert result.is_error


async def test_legacy_handshake_client_works(mcp_url):
    # Other SDKs (including Node) may still use the initialize handshake.
    async with Client(mcp_url, mode="legacy") as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"result": 5}


async def test_spcs_host_header_allowed(mcp_url):
    # Inside SPCS the client addresses the server as mcp-server:8000.
    async with httpx.AsyncClient() as http:
        r = await http.post(mcp_url, json=INITIALIZE, headers={**MCP_HEADERS, "Host": "mcp-server:8000"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "spcs-add-server"


async def test_unknown_host_header_rejected(mcp_url):
    # Proves DNS-rebinding protection is on rather than disabled.
    async with httpx.AsyncClient() as http:
        r = await http.post(mcp_url, json=INITIALIZE, headers={**MCP_HEADERS, "Host": "evil.example:8000"})
    assert r.status_code == 421
