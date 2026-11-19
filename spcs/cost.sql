-- What the demo cost, per pattern, over the last N days. Run as ACCOUNTADMIN (or a role with
-- SNOWFLAKE.USAGE_VIEWER). ACCOUNT_USAGE views lag by up to a few hours.
--
-- Attribution:
--   B1 AI functions    : QUERY_TAG 'spcs-mcp-demo' (set on every MCP_SERVER session)
--   B2 ask_agent       : agent MCP_DEMO_AGENT (any caller: MCP_SERVER, people, consumer role)
--   B3 ask_coding_agent: inline AGENT_RUN calls have no agent name, so: user MCP_SERVER, no agent
--   B4 coco_task       : Cortex Code CLI requests from the worker's service user COCO_WORKER
--   compute            : the two compute pools, plus the warehouse the SQL functions run on
SET days = 7;

WITH ai_functions AS (
  SELECT 'B1 AI functions' AS pattern, FUNCTION_NAME || ' ' || MODEL_NAME AS detail,
         COUNT(*) AS calls, SUM(CREDITS) AS credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
  WHERE START_TIME >= DATEADD('day', -$days, CURRENT_TIMESTAMP()) AND QUERY_TAG = 'spcs-mcp-demo'
  GROUP BY ALL
),
agents AS (
  SELECT CASE WHEN AGENT_NAME = 'MCP_DEMO_AGENT' THEN 'B2 ask_agent / MCP_DEMO_AGENT'
              ELSE 'B3 ask_coding_agent (inline AGENT_RUN)' END AS pattern,
         'user ' || USER_NAME AS detail, COUNT(*) AS calls, SUM(TOKEN_CREDITS) AS credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
  WHERE START_TIME >= DATEADD('day', -$days, CURRENT_TIMESTAMP())
    AND (AGENT_NAME = 'MCP_DEMO_AGENT' OR (USER_NAME = 'MCP_SERVER' AND COALESCE(AGENT_NAME, '') = ''))
  GROUP BY ALL
),
coco_cli AS (
  SELECT 'B4 coco_task (Cortex Code CLI)' AS pattern, 'user ' || USER_NAME AS detail,
         COUNT(*) AS calls, SUM(TOKEN_CREDITS) AS credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
  WHERE USAGE_TIME >= DATEADD('day', -$days, CURRENT_TIMESTAMP()) AND USER_NAME = 'COCO_WORKER'
  GROUP BY ALL
),
pools AS (
  SELECT 'compute pool' AS pattern, COMPUTE_POOL_NAME AS detail, COUNT(*) AS calls, SUM(CREDITS_USED) AS credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWPARK_CONTAINER_SERVICES_HISTORY
  WHERE START_TIME >= DATEADD('day', -$days, CURRENT_TIMESTAMP())
    AND COMPUTE_POOL_NAME IN ('MCP_DEMO_POOL', 'MCP_COCO_POOL')
  GROUP BY ALL
),
warehouse AS (
  SELECT 'warehouse' AS pattern, WAREHOUSE_NAME AS detail, COUNT(*) AS calls, SUM(CREDITS_USED) AS credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE START_TIME >= DATEADD('day', -$days, CURRENT_TIMESTAMP()) AND WAREHOUSE_NAME = 'MCP_DEMO_WH'
  GROUP BY ALL
)
SELECT pattern, detail, calls, ROUND(credits, 4) AS credits FROM ai_functions
UNION ALL SELECT pattern, detail, calls, ROUND(credits, 4) FROM agents
UNION ALL SELECT pattern, detail, calls, ROUND(credits, 4) FROM coco_cli
UNION ALL SELECT pattern, detail, calls, ROUND(credits, 4) FROM pools
UNION ALL SELECT pattern, detail, calls, ROUND(credits, 4) FROM warehouse
ORDER BY pattern, credits DESC;
