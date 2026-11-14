#!/usr/bin/env bash
# Roll one service to a new image tag in place. ALTER SERVICE keeps the service, so the
# client's ingress URL survives. The spec file is updated too, so it always matches what runs.
# Usage: bash scripts/build_push.sh v2 && bash scripts/deploy.sh client v2
set -euo pipefail
cd "$(dirname "$0")/.."

which="${1:-}"
tag="${2:-}"
case "$which" in
  server) service=MCP_SERVER; image=mcp-server ;;
  client) service=MCP_CLIENT; image=mcp-client ;;
  *) echo "usage: deploy.sh <server|client> <tag>"; exit 2 ;;
esac
[[ -n "$tag" ]] || { echo "usage: deploy.sh <server|client> <tag>"; exit 2; }

CONNECTION="${SNOW_CONNECTION:?set SNOW_CONNECTION to your snow CLI connection name}"
spec="spcs/$image.spec.yaml"
fqn="MCP_SPCS_DEMO.APP.$service"

python3 - "$spec" "$image" "$tag" <<'PY'
import re, sys
path, image, tag = sys.argv[1:]
text = open(path).read()
new, n = re.subn(rf"(/images/{image}):[A-Za-z0-9._-]+", rf"\g<1>:{tag}", text)
if n != 1:
    sys.exit(f"expected one {image} image line in {path}, found {n}")
open(path, "w").write(new)
PY

echo "== ALTER SERVICE $fqn -> $image:$tag"
rendered="$(cat "$spec")"
if [[ "$which" == server ]]; then
  # The public endpoint's Host header is its ingress hostname, which is account-specific and
  # only known once SPCS provisions it, so it is filled in here rather than kept in the spec.
  host=$(snow sql -c "$CONNECTION" --role MCP_DEMO_ROLE --format json -q "SHOW ENDPOINTS IN SERVICE $fqn" |
    python3 -c "import json,sys; print(next((r['ingress_url'] for r in json.load(sys.stdin) if r['name'] == 'mcp-public' and (r['ingress_url'] or '').endswith('.snowflakecomputing.app')), ''))")
  if [[ -z "$host" ]]; then
    echo "   note: mcp-public ingress is not provisioned yet; deploy again once SHOW ENDPOINTS lists it"
  else
    echo "   public ingress host: $host"
  fi
  rendered="${rendered//__PUBLIC_INGRESS_HOST__/$host}"
fi
snow sql -c "$CONNECTION" --role MCP_DEMO_ROLE -q "ALTER SERVICE $fqn FROM SPECIFICATION \$\$
$rendered
\$\$"

echo "== waiting for READY on $image:$tag"
for _ in $(seq 1 60); do
  status=$(snow sql -c "$CONNECTION" --role MCP_DEMO_ROLE --format json \
    -q "SHOW SERVICE CONTAINERS IN SERVICE $fqn" |
    python3 -c "import json,sys; r=json.load(sys.stdin)[0]; print(r['status'], r['image_name'].rsplit(':',1)[-1])")
  echo "   $status"
  if [[ "$status" == "READY $tag" ]]; then
    echo "DEPLOYED $fqn $image:$tag"
    exit 0
  fi
  sleep 10
done
echo "TIMED OUT waiting for $fqn to be READY on $tag"
exit 1
