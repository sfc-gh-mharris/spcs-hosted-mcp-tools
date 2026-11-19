#!/usr/bin/env bash
# Build images for linux/amd64 and push them to MCP_SPCS_DEMO.APP.IMAGES.
# Usage: bash scripts/build_push.sh <tag> [image ...]
#   bash scripts/build_push.sh v9                 # mcp-server and mcp-client
#   bash scripts/build_push.sh w1 coco-worker     # just the Cortex Code worker
# Use a new tag for every change so ALTER SERVICE picks up the new image predictably.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:?usage: build_push.sh <tag> [image ...]}"
shift
IMAGES=("$@")
[[ ${#IMAGES[@]} -gt 0 ]] || IMAGES=(mcp-server mcp-client)
CONNECTION="${SNOW_CONNECTION:?set SNOW_CONNECTION to your snow CLI connection name}"
REGISTRY="$(snow spcs image-registry url -c "$CONNECTION")"
REPO="$REGISTRY/mcp_spcs_demo/app/images"

snow spcs image-registry login -c "$CONNECTION"

for name in "${IMAGES[@]}"; do
  [[ -f "./$name/Dockerfile" ]] || { echo "no Dockerfile in ./$name"; exit 2; }
  echo "== $name:$TAG"
  docker build --platform linux/amd64 -t "$name:local" "./$name"
  docker tag "$name:local" "$REPO/$name:$TAG"
  docker push "$REPO/$name:$TAG"
done

echo "PUSHED $REPO/{$(IFS=,; echo "${IMAGES[*]}")}:$TAG"
