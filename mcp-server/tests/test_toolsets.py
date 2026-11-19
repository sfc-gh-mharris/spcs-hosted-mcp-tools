"""Private and public toolsets, the inbound call log, and the public host allow-list.

The conftest server runs both listeners; PUBLIC_HOST below is in its MCP_PUBLIC_ALLOWED_HOSTS,
standing in for the SPCS ingress hostname Snowflake forwards.
"""

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from mcp_server.calllog import CallRecorder

pytestmark = pytest.mark.anyio

PUBLIC_HOST = "ingress.example.snowflakecomputing.app"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def _tool_names(url: str) -> set[str]:
    async with Client(url) as client:
        return {t.name for t in (await client.list_tools()).tools}


async def test_public_endpoint_exposes_only_consumer_tools(public_mcp_url):
    assert await _tool_names(public_mcp_url) == {"add"}


async def test_private_endpoint_exposes_everything(mcp_url):
    names = await _tool_names(mcp_url)
    assert {"add", "snowflake_whoami"} <= names


async def test_public_calls_are_recorded_with_endpoint_and_caller(base_url, public_mcp_url):
    before = httpx.get(f"{base_url}/calls").json()["last_id"]
    http = create_mcp_http_client(headers={"Sf-Context-Current-User": "TEST_USER"})
    async with http:
        async with Client(streamable_http_client(public_mcp_url, http_client=http)) as client:
            result = await client.call_tool("add", {"a": 40, "b": 2})
    assert result.structured_content == {"result": 42}

    entries = httpx.get(f"{base_url}/calls", params={"since": before}).json()["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["endpoint"] == "public"
    assert entry["tool"] == "add"
    assert entry["args"] == {"a": 40, "b": 2}
    assert entry["caller"] == "TEST_USER"
    assert entry["ok"] is True
    assert entry["result"] == {"result": 42}
    assert entry["latency_ms"] >= 0


async def test_private_calls_are_recorded_too(base_url, mcp_url):
    before = httpx.get(f"{base_url}/calls").json()["last_id"]
    async with Client(mcp_url) as client:
        await client.call_tool("add", {"a": 1, "b": 1})
    entries = httpx.get(f"{base_url}/calls", params={"since": before}).json()["entries"]
    assert [(e["endpoint"], e["tool"], e["caller"]) for e in entries] == [("private", "add", None)]


async def test_failed_calls_are_recorded_as_errors(base_url, public_mcp_url):
    before = httpx.get(f"{base_url}/calls").json()["last_id"]
    async with Client(public_mcp_url) as client:
        result = await client.call_tool("add", {"a": "x", "b": 1})
    assert result.is_error
    entry = httpx.get(f"{base_url}/calls", params={"since": before}).json()["entries"][0]
    assert entry["ok"] is False
    assert "validation" in entry["error"].lower()


def test_call_log_is_not_served_on_the_public_port(public_base_url):
    assert httpx.get(f"{public_base_url}/calls").status_code == 404


def test_public_port_has_its_own_health_route(public_base_url):
    assert httpx.get(f"{public_base_url}/healthz").json()["endpoint"] == "public"


def test_public_endpoint_accepts_the_configured_ingress_host(public_mcp_url):
    r = httpx.post(public_mcp_url, json=INITIALIZE, headers={**MCP_HEADERS, "Host": PUBLIC_HOST})
    assert r.status_code == 200, r.text


def test_public_endpoint_rejects_other_hosts(public_mcp_url):
    r = httpx.post(public_mcp_url, json=INITIALIZE, headers={**MCP_HEADERS, "Host": "mcp-server:8001"})
    assert r.status_code == 421


def test_recorder_since_capacity_and_truncation():
    rec = CallRecorder(capacity=3, max_value_chars=20)
    for i in range(5):
        rec.record(endpoint="public", tool="t", args={"text": "x" * 100}, ok=True, result={"n": i},
                   error=None, latency_ms=1.0, caller=None, protocol="p")
    entries = rec.since(0)
    assert [e["id"] for e in entries] == [3, 4, 5]
    assert [e["id"] for e in rec.since(4)] == [5]
    assert len(entries[0]["args"]["text"]) <= 20 + len("...(truncated)")
    assert rec.last_id == 5
