#!/usr/bin/env bash
# Create the COCO_WORKER service from spcs/coco-worker.spec.yaml (one time; later changes use
# `bash scripts/deploy.sh worker <tag>`). Needs spcs/03_coco_pool.sql run first.
# Usage: SNOW_CONNECTION=<conn> bash scripts/create_worker.sh
set -euo pipefail
cd "$(dirname "$0")/.."
CONNECTION="${SNOW_CONNECTION:?set SNOW_CONNECTION to your snow CLI connection name}"

snow sql -c "$CONNECTION" --role MCP_DEMO_ROLE -q "CREATE SERVICE IF NOT EXISTS MCP_SPCS_DEMO.APP.COCO_WORKER
  IN COMPUTE POOL MCP_COCO_POOL
  FROM SPECIFICATION \$\$
$(cat spcs/coco-worker.spec.yaml)
\$\$
  QUERY_WAREHOUSE = MCP_DEMO_WH
  MIN_INSTANCES = 1
  MAX_INSTANCES = 1
  COMMENT = 'Cortex Code CLI worker for MCP_SERVER coco_task'"

echo "== waiting for READY"
for _ in $(seq 1 60); do
  status=$(snow sql -c "$CONNECTION" --role MCP_DEMO_ROLE --format json \
    -q "SHOW SERVICE CONTAINERS IN SERVICE MCP_SPCS_DEMO.APP.COCO_WORKER" |
    python3 -c "import json,sys; r=json.load(sys.stdin); print(r[0]['status'] if r else 'PENDING')")
  echo "   $status"
  [[ "$status" == READY ]] && { echo "CREATED MCP_SPCS_DEMO.APP.COCO_WORKER"; exit 0; }
  sleep 10
done
echo "TIMED OUT waiting for COCO_WORKER"
exit 1
