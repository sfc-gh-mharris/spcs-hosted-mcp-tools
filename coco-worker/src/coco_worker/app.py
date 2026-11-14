"""HTTP surface for the worker. Private endpoint only: MCP_SERVER's coco_task tool calls POST /run.

POST /run        {prompt, max_turns?} -> one Cortex Code run, or 429 if one is already running
GET  /healthz    readiness, no CLI involved
GET  /selfcheck  CLI version and the connection config SPCS generated; ?deep=1 also runs a tiny task
"""

import asyncio
import os
import tomllib
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from coco_worker.runner import RunSettings, run_task

MAX_PROMPT_CHARS = 8000
MAX_TURNS = 12
DEFAULT_TURNS = 6
SELFCHECK_PROMPT = "Run SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE() and reply with the three values."

RunFn = Callable[[str, int, float, RunSettings], Awaitable[dict[str, Any]]]


async def cli_version(cli_path: str | None) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        cli_path or "cortex", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    return out.decode(errors="replace").strip() or None


def describe_connections(env: Mapping[str, str]) -> dict[str, Any] | None:
    """Which connections.toml the CLI will see, and its key names (never values: it names the token file)."""
    candidates = []
    if env.get("SNOWFLAKE_HOME"):
        candidates.append(Path(env["SNOWFLAKE_HOME"]) / "connections.toml")
    candidates.append(Path.home() / ".snowflake" / "connections.toml")
    for path in candidates:
        if path.is_file():
            data = tomllib.loads(path.read_text())
            default = data.get("default", {})
            return {"path": str(path), "connections": sorted(data), "default_keys": sorted(default)}
    return None


def create_app(settings: RunSettings, run: RunFn | None = run_task, cli_version=cli_version,
               env: Mapping[str, str] = os.environ) -> Starlette:
    busy = asyncio.Lock()

    async def run_endpoint(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)
        prompt = body.get("prompt") if isinstance(body, dict) else None
        max_turns = body.get("max_turns", DEFAULT_TURNS) if isinstance(body, dict) else None
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            return JSONResponse({"error": f"prompt must be a non-empty string up to {MAX_PROMPT_CHARS} chars"}, 400)
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or not 1 <= max_turns <= MAX_TURNS:
            return JSONResponse({"error": f"max_turns must be an integer from 1 to {MAX_TURNS}"}, 400)
        # One CLI process at a time keeps memory bounded on a small node.
        if busy.locked():
            return JSONResponse({"error": "worker is busy with another run; try again shortly"}, status_code=429)
        async with busy:
            return JSONResponse(await run(prompt, max_turns, settings.max_seconds, settings))

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "busy": busy.locked()})

    async def selfcheck(request: Request) -> JSONResponse:
        body: dict[str, Any] = {"connection": settings.connection, "model": settings.model}
        try:
            body["cli_version"] = await cli_version(settings.cli_path)
        except Exception as exc:
            body["cli_version"] = None
            body["cli_error"] = f"{type(exc).__name__}: {exc}"
        body["connections_toml"] = describe_connections({**env, **settings.cli_env})
        if request.query_params.get("deep") and run is not None:
            if busy.locked():
                return JSONResponse({**body, "error": "worker is busy"}, status_code=429)
            async with busy:
                body["deep"] = await run(SELFCHECK_PROMPT, 3, min(settings.max_seconds, 180), settings)
        return JSONResponse(body)

    return Starlette(routes=[
        Route("/run", run_endpoint, methods=["POST"]),
        Route("/healthz", healthz, methods=["GET"]),
        Route("/selfcheck", selfcheck, methods=["GET"]),
    ])
