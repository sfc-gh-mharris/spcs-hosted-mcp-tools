-- Stop all billing for the demo without losing anything. Resume with resume.sql.
--
-- AUTO_RESUME goes off first. Otherwise any open monitor tab (it polls every 2 s) hits the
-- public endpoint and wakes MCP_CLIENT and the pool within seconds, while MCP_SERVER stays
-- down because service-to-service calls do not trigger auto-resume. Observed 2026-11-13.
USE ROLE MCP_DEMO_ROLE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_CLIENT SET AUTO_RESUME = FALSE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER SET AUTO_RESUME = FALSE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_CLIENT SUSPEND;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER SUSPEND;

-- MCP_DEMO_ROLE has USAGE and MONITOR only; the pool owner suspends it.
USE ROLE ACCOUNTADMIN;
ALTER COMPUTE POOL MCP_DEMO_POOL SUSPEND;
