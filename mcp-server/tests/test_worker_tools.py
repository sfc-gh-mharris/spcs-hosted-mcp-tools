"""coco_task (pattern B4): hand a prompt to the COCO_WORKER service and shape its answer."""

import httpx
import pytest
from fakes import FakeRunner
from mcp import Client

from mcp_server.server import build_mcp
from mcp_server.worker_tools import WorkerClient

pytestmark = pytest.mark.anyio

WORKER_OK = {
    "ok": True, "subtype": "success", "answer": "There are 0 tables in MCP_SPCS_DEMO.APP.", "error": None,
    "turns": 2, "duration_ms": 13598, "model": "claude-sonnet-5",
    "usage": {"input_tokens": 410, "output_tokens": 242, "cache_read_input_tokens": 58848},
    "tool_uses": [{"name": "sql_execute", "input": {"sql": "SHOW TABLES IN SCHEMA MCP_SPCS_DEMO.APP"}}],
    "denials": [],
}


def _worker(handler):
    seen = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return WorkerClient("http://coco-worker:8000", transport=httpx.MockTransport(record)), seen


async def _call(worker, args):
    async with Client(build_mcp(FakeRunner(), worker=worker)) as client:
        return await client.call_tool("coco_task", args)


async def test_posts_the_prompt_and_returns_the_shaped_answer():
    worker, seen = _worker(lambda r: httpx.Response(200, json=WORKER_OK))
    result = await _call(worker, {"prompt": "How many tables are in MCP_SPCS_DEMO.APP?", "max_turns": 4})
    assert not result.is_error, result.content
    data = result.structured_content
    assert data["answer"] == WORKER_OK["answer"]
    assert data["turns"] == 2
    assert data["tool_uses"] == ["sql_execute"]
    assert data["denials"] == []
    request = seen[0]
    assert str(request.url) == "http://coco-worker:8000/run"
    assert request.read() == b'{"prompt":"How many tables are in MCP_SPCS_DEMO.APP?","max_turns":4}'


async def test_busy_worker_is_a_tool_error():
    worker, _ = _worker(lambda r: httpx.Response(429, json={"error": "worker is busy with another run"}))
    result = await _call(worker, {"prompt": "x"})
    assert result.is_error
    assert "busy" in result.content[0].text


async def test_failed_runs_are_tool_errors_with_the_reason():
    failed = {**WORKER_OK, "ok": False, "subtype": "timeout", "error": "stopped after 300 s", "answer": ""}
    worker, _ = _worker(lambda r: httpx.Response(200, json=failed))
    result = await _call(worker, {"prompt": "x"})
    assert result.is_error
    assert "timeout" in result.content[0].text and "300 s" in result.content[0].text


async def test_unreachable_worker_is_a_tool_error():
    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    worker, _ = _worker(boom)
    result = await _call(worker, {"prompt": "x"})
    assert result.is_error
    assert "COCO_WORKER" in result.content[0].text


async def test_coco_task_is_not_on_the_public_toolset():
    worker, _ = _worker(lambda r: httpx.Response(200, json=WORKER_OK))
    async with Client(build_mcp(FakeRunner(), toolset="public", worker=worker)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "coco_task" not in names
