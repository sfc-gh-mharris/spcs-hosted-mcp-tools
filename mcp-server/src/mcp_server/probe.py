"""Smoke test an MCP server end to end: python -m mcp_server.probe --url http://mcp-server:8000/mcp

Always checks connect, tools/list, and add(2, 3). With --tool it also calls one more tool and
checks its structured result, so one image can verify any tool from inside SPCS:

    python -m mcp_server.probe --tool snowflake_whoami --expect role=MCP_DEMO_ROLE
    python -m mcp_server.probe --tool ask_agent --args '{"question": "..."}' --expect "answer~=42"

`key=value` is an exact match on str(value); `key~=value` is a substring match. Dotted keys
reach nested fields. Prints one PASS/FAIL line per check and exits 0 only if all pass.
"""

import argparse
import json
import os
import sys
from typing import Any

import anyio
from mcp import Client


def _lookup(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def _check_expectation(data: Any, expectation: str) -> tuple[bool, str]:
    contains = "~=" in expectation
    key, _, expected = expectation.partition("~=" if contains else "=")
    actual = _lookup(data, key)
    if contains:
        return expected in str(actual), f"{key}={actual!r}"
    # Compare numbers numerically so result=3.5 matches 3.5 and result=5 matches 5.0.
    try:
        return float(actual) == float(expected), f"{key}={actual!r}"
    except (TypeError, ValueError):
        return str(actual) == expected, f"{key}={actual!r}"


async def _run_checks(url: str, tool: str | None, args: dict, expectations: list[str]) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    async with Client(url) as client:
        name = client.server_info.name if client.server_info else "?"
        results.append(("connect", True, f"server={name} protocol={client.protocol_version}"))

        tool_names = [t.name for t in (await client.list_tools()).tools]
        results.append(("list_tools", "add" in tool_names, f"tools={tool_names}"))

        res = await client.call_tool("add", {"a": 2, "b": 3})
        value = (res.structured_content or {}).get("result")
        results.append(("call add(2, 3)", not res.is_error and value == 5, f"result={value}"))

        if tool:
            res = await client.call_tool(tool, args)
            text = " ".join(getattr(c, "text", "") for c in res.content)[:300]
            data = res.structured_content
            results.append((f"tool {tool}", not res.is_error, json.dumps(data, default=str)[:500] if data else text))
            for expectation in expectations:
                ok, detail = _check_expectation(data, expectation)
                results.append((f"expect {expectation}", ok and not res.is_error, detail))
    return results


async def _with_timeout(url: str, timeout: float, tool: str | None, args: dict, expectations: list[str]):
    with anyio.fail_after(timeout):
        return await _run_checks(url, tool, args, expectations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("MCP_SERVER_URL", "http://mcp-server:8000/mcp"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--tool", help="an extra tool to call after the add check")
    parser.add_argument("--args", default="{}", help="JSON arguments for --tool")
    parser.add_argument("--expect", action="append", default=[], help="key=value or key~=value on the result")
    args = parser.parse_args(argv)

    print(f"probing {args.url}" + (f" tool={args.tool}" if args.tool else ""), flush=True)
    try:
        results = anyio.run(_with_timeout, args.url, args.timeout, args.tool, json.loads(args.args), args.expect)
    except Exception as exc:  # unreachable host, timeout, protocol error: all count as failure
        print(f"FAIL connect: {type(exc).__name__}: {exc}", flush=True)
        print("PROBE FAILED", flush=True)
        return 1

    for check, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {check}: {detail}", flush=True)
    passed = all(ok for _, ok, _ in results)
    print("PROBE PASSED" if passed else "PROBE FAILED", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
