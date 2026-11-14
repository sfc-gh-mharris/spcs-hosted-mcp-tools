-- Step 2, pattern B4: a separate pool and service for the Cortex Code worker. Safe to re-run.
-- Run after 01_cortex_setup.sql and `bash scripts/build_push.sh w1 coco-worker`.
-- The worker gets its own pool so a long CLI run cannot starve MCP_SERVER or MCP_CLIENT.

USE ROLE ACCOUNTADMIN;
CREATE COMPUTE POOL IF NOT EXISTS MCP_COCO_POOL
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = CPU_X64_XS
  INITIALLY_SUSPENDED = TRUE
  AUTO_RESUME = TRUE
  AUTO_SUSPEND_SECS = 600
  COMMENT = 'SPCS MCP demo: COCO_WORKER (Cortex Code CLI)';
GRANT USAGE, MONITOR ON COMPUTE POOL MCP_COCO_POOL TO ROLE MCP_DEMO_ROLE;

-- Same owner role as MCP_SERVER, so service-to-service calls need no extra grants. The CLI's
-- SQL runs as the worker's service user under MCP_DEMO_ROLE, on QUERY_WAREHOUSE.
-- Create the service with the spec file (snow sql substitutes nothing, so paste it or use
-- scripts/create_worker.sh):
--   CREATE SERVICE IF NOT EXISTS MCP_SPCS_DEMO.APP.COCO_WORKER
--     IN COMPUTE POOL MCP_COCO_POOL
--     FROM SPECIFICATION $$ <contents of spcs/coco-worker.spec.yaml> $$
--     QUERY_WAREHOUSE = MCP_DEMO_WH
--     MIN_INSTANCES = 1 MAX_INSTANCES = 1;
