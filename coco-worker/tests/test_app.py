"""HTTP surface: /run validation, one run at a time (429), /healthz, /selfcheck."""

import asyncio

import httpx
import pytest

from coco_worker.app import create_app
from coco_worker.runner import RunSettings

pytestmark = pytest.mark.anyio

SETTINGS = RunSettings(connection="default", model="claude-sonnet-5", cli_path="/usr/local/bin/cortex", workdir="/tmp")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker")


async def test_run_returns_the_shaped_result():
    calls = []

    async def fake_run(prompt, max_turns, timeout_s, settings):
        calls.append((prompt, max_turns, timeout_s))
        return {"ok": True, "answer": "42", "turns": 1}

    async with _client(create_app(SETTINGS, run=fake_run)) as client:
        r = await client.post("/run", json={"prompt": "hi", "max_turns": 4})
    assert r.status_code == 200
    assert r.json()["answer"] == "42"
    assert calls == [("hi", 4, SETTINGS.max_seconds)]


@pytest.mark.parametrize("body", [{}, {"prompt": ""}, {"prompt": 5}, {"prompt": "x", "max_turns": 0},
                                  {"prompt": "x", "max_turns": 99}, {"prompt": "x" * 9000}])
async def test_run_validates_input(body):
    async def never(*_):
        raise AssertionError("should not run")

    async with _client(create_app(SETTINGS, run=never)) as client:
        r = await client.post("/run", json=body)
    assert r.status_code == 400


async def test_a_second_run_while_one_is_active_gets_429():
    release = asyncio.Event()

    async def slow_run(prompt, max_turns, timeout_s, settings):
        await release.wait()
        return {"ok": True, "answer": prompt}

    app = create_app(SETTINGS, run=slow_run)
    async with _client(app) as client:
        first = asyncio.create_task(client.post("/run", json={"prompt": "first"}))
        await asyncio.sleep(0.05)
        second = await client.post("/run", json={"prompt": "second"})
        release.set()
        first_response = await first
    assert second.status_code == 429
    assert first_response.status_code == 200


async def test_healthz_does_not_touch_the_cli():
    async with _client(create_app(SETTINGS, run=None)) as client:
        r = await client.get("/healthz")
    assert r.json()["status"] == "ok"


async def test_selfcheck_reports_cli_version_and_connection_config(tmp_path):
    home = tmp_path / "sfhome"
    home.mkdir()
    (home / "connections.toml").write_text('[default]\naccount = "A"\nauthenticator = "OAUTH"\ntoken_file_path = "/t"\n')

    async def fake_version(cli_path):
        return "1.2.45+061229.2a20c0482251"

    app = create_app(SETTINGS, run=None, cli_version=fake_version, env={"SNOWFLAKE_HOME": str(home)})
    async with _client(app) as client:
        r = await client.get("/selfcheck")
    body = r.json()
    assert body["cli_version"].startswith("1.2.45")
    assert body["connections_toml"] == {"path": str(home / "connections.toml"), "connections": ["default"],
                                        "default_keys": ["account", "authenticator", "token_file_path"]}
    assert "deep" not in body


async def test_deep_selfcheck_runs_a_real_task():
    async def fake_run(prompt, max_turns, timeout_s, settings):
        return {"ok": True, "answer": "MCP_COCO_WORKER | MCP_DEMO_ROLE", "turns": 1}

    async def fake_version(cli_path):
        return "1.2.45"

    app = create_app(SETTINGS, run=fake_run, cli_version=fake_version, env={})
    async with _client(app) as client:
        r = await client.get("/selfcheck", params={"deep": "1"})
    assert r.json()["deep"]["ok"] is True
