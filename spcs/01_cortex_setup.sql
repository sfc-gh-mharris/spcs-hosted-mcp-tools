-- Step 2 prerequisites: a warehouse and Cortex access for MCP_DEMO_ROLE. Safe to re-run.
-- Run as ACCOUNTADMIN after 00_setup.sql. The warehouse starts suspended.

USE ROLE ACCOUNTADMIN;

-- SQL from the MCP server (AI functions, DATA_AGENT_RUN, AGENT_RUN) needs a warehouse.
CREATE WAREHOUSE IF NOT EXISTS MCP_DEMO_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'SPCS MCP demo: Cortex calls from MCP_SERVER';
GRANT OWNERSHIP ON WAREHOUSE MCP_DEMO_WH TO ROLE MCP_DEMO_ROLE COPY CURRENT GRANTS;

-- Covers AI_* functions and Cortex Agents. USE AI FUNCTIONS is granted to PUBLIC by default.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MCP_DEMO_ROLE;

-- The service user picks this warehouse up on its next restart (the next deploy).
USE ROLE MCP_DEMO_ROLE;
ALTER SERVICE IF EXISTS MCP_SPCS_DEMO.APP.MCP_SERVER SET QUERY_WAREHOUSE = MCP_DEMO_WH;
