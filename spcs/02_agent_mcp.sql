-- Step 2 spike: let Snowflake (CoCo and Cortex Agents) call MCP_SERVER's public toolset.
-- Run after 00_setup.sql, 01_cortex_setup.sql, and a deploy with the mcp-public endpoint.
-- Safe to re-run.
--
-- What each consumer needs, per the SPCS-hosted MCP server docs:
--   CoCo (direct ingress):   endpoint access only (service role mcp_consumer).
--   Cortex Agent:            USAGE on the agent and the CUSTOM MCP SERVER object, plus endpoint
--                            access. Snowflake checks the MCP server owner role too.
-- The agent spec lives in cortex_project/spcs/MCP_DEMO_AGENT.agent.yaml (deployed with
-- `cortex agent-studio agent-deploy`, then ownership moved to MCP_DEMO_ROLE).

USE ROLE MCP_DEMO_ROLE;
USE SCHEMA MCP_SPCS_DEMO.APP;

-- Registers the public endpoint for Cortex Agents. Documented for Native Apps; also works
-- standalone. DESC shows the resolved ingress URL.
CREATE CUSTOM MCP SERVER IF NOT EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC
  SERVICE = MCP_SPCS_DEMO.APP.MCP_SERVER
  ENDPOINT = "mcp-public"
  PATH = '/mcp'
  COMMENT = 'SPCS-hosted MCP server: public toolset of MCP_SERVER for CoCo and Cortex Agents';

-- A least-privilege consumer: can chat with the demo agent and reach the public toolset,
-- nothing else. Granted to whoever runs this script.
USE ROLE ACCOUNTADMIN;
-- agent-deploy creates the agent as the connection's role; the demo role should own it.
GRANT OWNERSHIP ON AGENT MCP_SPCS_DEMO.APP.MCP_DEMO_AGENT TO ROLE MCP_DEMO_ROLE COPY CURRENT GRANTS;
CREATE ROLE IF NOT EXISTS MCP_DEMO_CONSUMER_ROLE COMMENT = 'Calls the SPCS MCP demo public toolset';
SET deploy_user = CURRENT_USER();
GRANT ROLE MCP_DEMO_CONSUMER_ROLE TO USER IDENTIFIER($deploy_user);
-- Running an agent needs Cortex access. Many accounts grant this to PUBLIC by default;
-- granting it explicitly keeps the recipe working where an admin has revoked that.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MCP_DEMO_CONSUMER_ROLE;

USE ROLE MCP_DEMO_ROLE;
GRANT USAGE ON DATABASE MCP_SPCS_DEMO TO ROLE MCP_DEMO_CONSUMER_ROLE;
GRANT USAGE ON SCHEMA MCP_SPCS_DEMO.APP TO ROLE MCP_DEMO_CONSUMER_ROLE;
GRANT USAGE ON AGENT MCP_SPCS_DEMO.APP.MCP_DEMO_AGENT TO ROLE MCP_DEMO_CONSUMER_ROLE;
GRANT USAGE ON CUSTOM MCP SERVER MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC TO ROLE MCP_DEMO_CONSUMER_ROLE;
GRANT SERVICE ROLE MCP_SPCS_DEMO.APP.MCP_SERVER!MCP_CONSUMER TO ROLE MCP_DEMO_CONSUMER_ROLE;
-- DATA_AGENT_RUN is a SQL function, so the session needs a warehouse.
GRANT USAGE ON WAREHOUSE MCP_DEMO_WH TO ROLE MCP_DEMO_CONSUMER_ROLE;
