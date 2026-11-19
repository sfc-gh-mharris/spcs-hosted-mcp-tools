#!/usr/bin/env python3
"""Stage 6 gate: call the MCP_CLIENT public endpoint programmatically with a PAT.

Usage: SNOW_CONNECTION=<conn> python3 scripts/smoke_spcs.py [--url https://<ingress>] [--connection NAME]
       [--soak SECONDS] [--cortex] [--agents]

The PAT comes from SNOWFLAKE_PAT if set, otherwise from the `token` field of the named
connection in ~/.snowflake/connections.toml. It is held in memory only and never printed.
Without --url, the ingress URL is looked up with `snow sql` as MCP_DEMO_ROLE.
--soak runs the traffic generator at 1 s and polls like the UI does (every 2 s) for that many
seconds, to show the call log keeps flowing past the 90 s ingress idle timeout.
--cortex runs each AI function tool as a background job through the monitor, the way the UI does.
--agents also runs ask_agent, ask_coding_agent, and coco_task (tens of seconds and real credits each).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect here means Snowflake wants an interactive login, i.e. the PAT was not accepted.
    def redirect_request(self, *args, **kwargs):
        return None


def load_pat(connection: str) -> str:
    if os.environ.get("SNOWFLAKE_PAT"):
        return os.environ["SNOWFLAKE_PAT"]
    config = tomllib.loads((Path.home() / ".snowflake" / "connections.toml").read_text())
    token = config.get(connection, {}).get("token")
    if not token:
        sys.exit(f"no SNOWFLAKE_PAT and no token for connection {connection!r}")
    return token


def lookup_ingress(connection: str) -> str:
    out = subprocess.run(
        ["snow", "sql", "-c", connection, "--role", "MCP_DEMO_ROLE", "--format", "json",
         "-q", "SHOW ENDPOINTS IN SERVICE MCP_SPCS_DEMO.APP.MCP_CLIENT"],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = json.loads(out)
    url = next(r["ingress_url"] for r in rows if r["name"] == "ui")
    if "provisioning" in url.lower():
        sys.exit(f"endpoint not ready: {url}")
    return f"https://{url}"


def request(opener, base: str, pat: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method="POST" if data else "GET")
    req.add_header("Authorization", f'Snowflake Token="{pat}"')
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=30) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, {"error": err.read().decode(errors="replace")[:300], "location": err.headers.get("Location")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url")
    parser.add_argument("--connection", default=os.environ.get("SNOW_CONNECTION"),
                        help="snow CLI connection name (default: $SNOW_CONNECTION)")
    parser.add_argument("--soak", type=int, default=0, metavar="SECONDS")
    parser.add_argument("--cortex", action="store_true", help="run each AI function tool once as a job")
    parser.add_argument("--agents", action="store_true", help="also run the agent and Cortex Code tools")
    args = parser.parse_args()
    if not args.connection:
        parser.error("set SNOW_CONNECTION or pass --connection")

    base = (args.url or lookup_ingress(args.connection)).rstrip("/")
    pat = load_pat(args.connection)
    opener = urllib.request.build_opener(_NoRedirect)
    print(f"target {base}")

    failures = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    status, body = request(opener, base, pat, "/healthz")
    check("healthz through ingress", status == 200, f"status={status} body={body}")

    status, body = request(opener, base, pat, "/api/tools")
    names = [t["name"] for t in body.get("tools", [])]
    check("tools via MCP", status == 200 and "add" in names, f"status={status} tools={names}")

    status, body = request(opener, base, pat, "/api/call", {"a": 2, "b": 3})
    check("add(2, 3) = 5", status == 200 and body.get("result") == 5,
          f"status={status} result={body.get('result')} latencyMs={body.get('latencyMs')}")

    status, body = request(opener, base, pat, "/api/status")
    server = (body.get("serverInfo") or {}).get("name")
    check("client connected to MCP_SERVER", status == 200 and body.get("connected") and server == "spcs-add-server",
          f"server={server} protocol={body.get('protocolVersion')} url={body.get('url')}")

    if args.soak:
        soak(opener, base, pat, args.soak, check)

    if args.cortex or args.agents:
        jobs = list(CORTEX_JOBS) + (list(AGENT_JOBS) if args.agents else [])
        for tool, tool_args, expect in jobs:
            run_job(opener, base, pat, tool, tool_args, expect, check)

    print("SPCS SMOKE PASSED" if failures == 0 else f"SPCS SMOKE FAILED ({failures})")
    return 0 if failures == 0 else 1


# (tool, args, check on the result). Each runs as a background job: POST /api/jobs returns 202 and
# the entry is polled until done, so no single request waits on Cortex.
CORTEX_JOBS = [
    ("snowflake_whoami", {}, lambda r: r.get("role") == "MCP_DEMO_ROLE"),
    ("cortex_complete", {"prompt": "Reply with exactly: OK", "max_tokens": 8}, lambda r: "OK" in r.get("text", "")),
    ("cortex_classify", {"text": "My card was charged twice", "categories": ["billing", "shipping"]},
     lambda r: r.get("label") == "billing"),
    ("cortex_sentiment", {"text": "The demo went great"}, lambda r: r.get("sentiment") == "positive"),
]
AGENT_JOBS = [
    ("ask_agent", {"question": "What is 19.5 + 22.5? Use the add tool."},
     lambda r: "42" in r.get("answer", "") and any(u["name"].endswith("add") for u in r.get("tool_uses", []))),
    ("ask_coding_agent", {"task": "How many tables are in MCP_SPCS_DEMO.APP?", "max_seconds": 180},
     lambda r: bool(r.get("tool_uses"))),
    ("coco_task", {"prompt": "How many tables are in MCP_SPCS_DEMO.APP?", "max_turns": 4},
     lambda r: "sql_execute" in r.get("tool_uses", [])),
]


def run_job(opener, base: str, pat: str, tool: str, tool_args: dict, expect, check, wait_s: int = 600) -> None:
    status, body = request(opener, base, pat, "/api/jobs", {"tool": tool, "args": tool_args})
    if status != 202:
        check(f"job {tool}", False, f"status={status} body={body}")
        return
    job_id = body["entry"]["id"]
    deadline = time.monotonic() + wait_s
    entry = None
    while time.monotonic() < deadline:
        time.sleep(2)
        status, body = request(opener, base, pat, "/api/calls?sinceRev=0")
        entry = next((e for e in body.get("entries", []) if e["id"] == job_id), None)
        if entry and entry.get("status") == "done":
            break
    if not entry or entry.get("status") != "done":
        check(f"job {tool}", False, f"not done after {wait_s}s")
        return
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    ok = bool(entry.get("ok")) and expect(result)
    detail = json.dumps(entry.get("result") if entry.get("ok") else entry.get("error"), default=str)[:240]
    check(f"job {tool}", ok, f"{entry.get('latencyMs')} ms {detail}")


def soak(opener, base: str, pat: str, seconds: int, check) -> None:
    start_id = request(opener, base, pat, "/api/calls?since=0")[1]["stats"]["lastId"]
    status, body = request(opener, base, pat, "/api/traffic", {"enabled": True, "intervalMs": 1000})
    check("traffic on", status == 200 and body.get("enabled"), f"status={status} body={body}")
    poll_failures = 0
    polls = 0
    seen = 0
    errors = 0
    last_id = start_id
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(2)
            polls += 1
            status, body = request(opener, base, pat, f"/api/calls?since={last_id}")
            if status != 200:
                poll_failures += 1
                continue
            entries = body["entries"]
            seen += len(entries)
            errors += sum(1 for e in entries if not e["ok"])
            if entries:
                last_id = entries[-1]["id"]
            if polls % 15 == 0:
                print(f"   soak {polls * 2}s: {seen} calls, {errors} errors, {poll_failures} failed polls", flush=True)
    finally:
        request(opener, base, pat, "/api/traffic", {"enabled": False})
    expected = int(seconds * 0.8)
    check(f"soak {seconds}s", poll_failures == 0 and errors == 0 and seen >= expected,
          f"polls={polls} failed_polls={poll_failures} calls={seen} (>= {expected}) errors={errors}")


if __name__ == "__main__":
    sys.exit(main())
