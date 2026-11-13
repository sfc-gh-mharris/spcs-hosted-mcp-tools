-- Run the in-cluster probe against MCP_SERVER and read its result.
-- EXECUTE JOB SERVICE is synchronous: it returns when the probe container exits.
USE ROLE MCP_DEMO_ROLE;
USE SCHEMA MCP_SPCS_DEMO.APP;

DROP SERVICE IF EXISTS MCP_PROBE_JOB;

EXECUTE JOB SERVICE
  IN COMPUTE POOL MCP_DEMO_POOL
  NAME = MCP_SPCS_DEMO.APP.MCP_PROBE_JOB
  FROM SPECIFICATION $$
spec:
  containers:
  - name: probe
    image: /mcp_spcs_demo/app/images/mcp-server:v1
    command: ["python", "-m", "mcp_server.probe", "--url", "http://mcp-server:8000/mcp", "--timeout", "60"]
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 250m
        memory: 256Mi
$$;

-- Expect PASS lines and PROBE PASSED.
SELECT SYSTEM$GET_SERVICE_LOGS('MCP_SPCS_DEMO.APP.MCP_PROBE_JOB', 0, 'probe') AS probe_logs;

-- The server should log the probe's call: tool=add a=2 b=3 result=5.0
SELECT SYSTEM$GET_SERVICE_LOGS('MCP_SPCS_DEMO.APP.MCP_SERVER', 0, 'server', 20) AS server_logs;
