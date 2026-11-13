#!/usr/bin/env bash
# Stage 3 gate: build both amd64 images, run them on a compose network named like SPCS,
# and check the full browser-facing path plus the in-network probe.
# KEEP_UP=1 leaves the stack running afterwards for manual UI checks.
set -euo pipefail
cd "$(dirname "$0")/.."

CLIENT=http://localhost:8080
fail() { echo "FAIL $*"; exit 1; }
pass() { echo "PASS $*"; }

cleanup() {
  if [[ "${KEEP_UP:-0}" != "1" ]]; then docker compose down --remove-orphans >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

echo "== build and start (waits for healthchecks)"
docker compose up --build --detach --wait

echo "== checks"
curl -fsS "$CLIENT/healthz" >/dev/null && pass "client healthz" || fail "client healthz"

tools=$(curl -fsS "$CLIENT/api/tools")
python3 -c 'import json,sys; t=json.loads(sys.argv[1])["tools"]; sys.exit(0 if any(x["name"]=="add" for x in t) else 1)' "$tools" \
  && pass "client lists add via MCP" || fail "tools: $tools"

call=$(curl -sS -X POST -H 'Content-Type: application/json' -d '{"a":2,"b":3}' "$CLIENT/api/call")
python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("result")==5 else 1)' "$call" \
  && pass "client add(2,3) = 5 through mcp-server:8000" || fail "call: $call"

status=$(curl -fsS "$CLIENT/api/status")
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if d["connected"] and d["serverInfo"]["name"]=="spcs-add-server" else 1)' "$status" \
  && pass "client connected to spcs-add-server" || fail "status: $status"

if curl -fsS --max-time 2 http://localhost:8000/healthz >/dev/null 2>&1; then
  fail "mcp-server is reachable from the host; it should be network-internal"
else
  pass "mcp-server not exposed to the host"
fi

docker compose run --rm probe && pass "in-network probe" || fail "in-network probe"

docker compose logs mcp-server | grep -q "tool=add a=2" && pass "server logged the client's call" || fail "server log missing call"

echo "== image sizes"
docker image ls --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E '^mcp-(server|client):local'

echo "SMOKE PASSED"
