-- Stage 4: Snowflake foundation for the SPCS MCP demo. Safe to re-run.
-- Run as ACCOUNTADMIN. Creates nothing that bills: the pool starts suspended.

USE ROLE ACCOUNTADMIN;

-- One role owns both services, so service-to-service endpoint access needs no extra grants.
-- Granted to whoever runs this script; IDENTIFIER() resolves the session variable.
CREATE ROLE IF NOT EXISTS MCP_DEMO_ROLE COMMENT = 'Owns the SPCS MCP server and client demo services';
SET deploy_user = CURRENT_USER();
GRANT ROLE MCP_DEMO_ROLE TO USER IDENTIFIER($deploy_user);
GRANT ROLE MCP_DEMO_ROLE TO ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS MCP_SPCS_DEMO COMMENT = 'SPCS-hosted MCP server and client demo';
GRANT OWNERSHIP ON DATABASE MCP_SPCS_DEMO TO ROLE MCP_DEMO_ROLE COPY CURRENT GRANTS;

CREATE COMPUTE POOL IF NOT EXISTS MCP_DEMO_POOL
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = CPU_X64_XS
  INITIALLY_SUSPENDED = TRUE
  AUTO_RESUME = TRUE
  AUTO_SUSPEND_SECS = 600
  COMMENT = 'SPCS MCP demo: MCP_SERVER, MCP_CLIENT, probe jobs';
GRANT USAGE, MONITOR ON COMPUTE POOL MCP_DEMO_POOL TO ROLE MCP_DEMO_ROLE;

-- Required to create the client's public endpoint.
GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE MCP_DEMO_ROLE;

USE ROLE MCP_DEMO_ROLE;
CREATE SCHEMA IF NOT EXISTS MCP_SPCS_DEMO.APP;
CREATE IMAGE REPOSITORY IF NOT EXISTS MCP_SPCS_DEMO.APP.IMAGES COMMENT = 'mcp-server and mcp-client images';
