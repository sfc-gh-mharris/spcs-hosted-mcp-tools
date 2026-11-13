"""Smoke test an MCP server end to end: python -m mcp_server.probe --url http://mcp-server:8000/mcp

Prints one PASS/FAIL line per check and exits 0 only when every check passes, so it works
as a pytest subject locally and as an SPCS job service whose logs show the outcome.
"""

import argparse
import os
import sys

import anyio
from mcp import Client


async def _run_checks(url: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    async with Client(url) as client:
        name = client.server_info.name if client.server_info else "?"
        results.append(("connect", True, f"server={name} protocol={client.protocol_version}"))

        tool_names = [t.name for t in (await client.list_tools()).tools]
        results.append(("list_tools", "add" in tool_names, f"tools={tool_names}"))

        res = await client.call_tool("add", {"a": 2, "b": 3})
        value = (res.structured_content or {}).get("result")
        results.append(("call add(2, 3)", not res.is_error and value == 5, f"result={value}"))
    return results


async def _with_timeout(url: str, timeout: float) -> list[tuple[str, bool, str]]:
    with anyio.fail_after(timeout):
        return await _run_checks(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("MCP_SERVER_URL", "http://mcp-server:8000/mcp"))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    print(f"probing {args.url}", flush=True)
    try:
        results = anyio.run(_with_timeout, args.url, args.timeout)
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
