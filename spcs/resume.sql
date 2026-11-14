-- Bring the demo back after suspend.sql. Server and worker first so the client connects at
-- startup. Ingress URLs are unchanged, so the custom MCP server and the agent keep working.
USE ROLE MCP_DEMO_ROLE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER RESUME;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.COCO_WORKER RESUME;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_CLIENT RESUME;

-- Restore the default. Note AUTO_RESUME only reacts to ingress and service functions;
-- MCP_CLIENT calling MCP_SERVER (or MCP_SERVER calling COCO_WORKER) never wakes it, so
-- suspend and resume all services together.
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER SET AUTO_RESUME = TRUE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.COCO_WORKER SET AUTO_RESUME = TRUE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_CLIENT SET AUTO_RESUME = TRUE;
