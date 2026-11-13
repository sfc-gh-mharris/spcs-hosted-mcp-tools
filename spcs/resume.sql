-- Bring the demo back after suspend.sql. Server first so the client connects at startup.
-- The client's ingress URL is unchanged.
USE ROLE MCP_DEMO_ROLE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER RESUME;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_CLIENT RESUME;

-- Restore the default. Note AUTO_RESUME only reacts to ingress and service functions;
-- MCP_CLIENT calling MCP_SERVER never wakes it, so suspend/resume both services together.
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER SET AUTO_RESUME = TRUE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_CLIENT SET AUTO_RESUME = TRUE;
