#!/usr/bin/env python3
"""Run the MCP probe as a one-shot SPCS job and print its result.

Usage:
  SNOW_CONNECTION=<conn> python3 scripts/probe_spcs.py                       # connect, list, add
  SNOW_CONNECTION=<conn> python3 scripts/probe_spcs.py --tool snowflake_whoami --expect role=MCP_DEMO_ROLE
  SNOW_CONNECTION=<conn> python3 scripts/probe_spcs.py --tool ask_agent \\
      --args '{"question": "What is 19.5 + 22.5?"}' --expect "answer~=42" --timeout 600

The job reuses the image tag in spcs/mcp-server.spec.yaml unless --image-tag is given, runs as
MCP_DEMO_ROLE on MCP_DEMO_POOL, and calls the server over the SPCS internal network.
Exits 0 only if the probe logs PROBE PASSED.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOB = "MCP_SPCS_DEMO.APP.MCP_PROBE_JOB"


def snow_sql(connection: str, sql: str, fmt: str = "json", check: bool = True) -> str:
    out = subprocess.run(
        ["snow", "sql", "-c", connection, "--role", "MCP_DEMO_ROLE", "--format", fmt, "-q", sql],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        if check:
            sys.exit(f"snow sql failed:\n{out.stdout}\n{out.stderr}")
        return ""
    return out.stdout


def current_server_tag() -> str:
    spec = (ROOT / "spcs" / "mcp-server.spec.yaml").read_text()
    match = re.search(r"/images/mcp-server:([A-Za-z0-9._-]+)", spec)
    if not match:
        sys.exit("could not find the mcp-server image tag in spcs/mcp-server.spec.yaml")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection", default=os.environ.get("SNOW_CONNECTION"))
    parser.add_argument("--image-tag")
    parser.add_argument("--url", default="http://mcp-server:8000/mcp")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--tool")
    parser.add_argument("--args", default="{}")
    parser.add_argument("--expect", action="append", default=[])
    args = parser.parse_args()
    if not args.connection:
        parser.error("set SNOW_CONNECTION or pass --connection")
    json.loads(args.args)  # fail fast on bad JSON before starting a job

    command = ["python", "-m", "mcp_server.probe", "--url", args.url, "--timeout", str(args.timeout)]
    if args.tool:
        command += ["--tool", args.tool, "--args", args.args]
        for expectation in args.expect:
            command += ["--expect", expectation]

    tag = args.image_tag or current_server_tag()
    # YAML accepts JSON flow syntax, so json.dumps quotes every argument safely.
    spec = f"""spec:
  containers:
  - name: probe
    image: /mcp_spcs_demo/app/images/mcp-server:{tag}
    command: {json.dumps(command)}
    resources:
      requests: {{cpu: 100m, memory: 128Mi}}
      limits: {{cpu: 250m, memory: 256Mi}}
"""
    print(f"probe job on mcp-server:{tag}: {' '.join(command[3:]) or 'default checks'}", flush=True)
    snow_sql(args.connection, f"DROP SERVICE IF EXISTS {JOB}")
    status = snow_sql(
        args.connection,
        f"EXECUTE JOB SERVICE IN COMPUTE POOL MCP_DEMO_POOL NAME = {JOB} FROM SPECIFICATION $$\n{spec}$$",
        check=False,  # a failed job still has logs worth printing
    )
    print(json.loads(status)[0]["status"] if status else "job did not finish successfully", flush=True)
    logs = snow_sql(args.connection, f"SELECT SYSTEM$GET_SERVICE_LOGS('{JOB}', 0, 'probe') AS LOGS")
    text = json.loads(logs)[0]["LOGS"]
    print(text, flush=True)
    return 0 if "PROBE PASSED" in text else 1


if __name__ == "__main__":
    sys.exit(main())
