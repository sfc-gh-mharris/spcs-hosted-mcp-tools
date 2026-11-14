"""What the worker's Cortex Code session may do: read files and run read-only SQL, nothing else.

Two layers, because neither alone is enough:
- DISALLOWED_TOOLS removes tools from the model's context entirely (interactive prompts nobody
  can answer, shell, file writes, web access, skills).
- ReadOnlyPolicy.can_use_tool answers every permission check the CLI still raises, allowing only a
  single read-only SQL statement. The CLI's own ResultMessage.permission_denials came back empty
  when this callback denied a call, so denials are recorded here instead.

The service role's grants are the real boundary; this keeps the session from trying.
"""

import re
from typing import Any

from cortex_agent_sdk.cortexcode import PermissionResultAllow, PermissionResultDeny

DISALLOWED_TOOLS = [
    "ask_user_question", "enter_plan_mode", "exit_plan_mode",
    "bash", "bash_output", "kill_shell", "write", "edit", "notebook_actions",
    "web_fetch", "web_search", "skill",
    "task", "task_create", "team_create", "spawn_teammate", "send_message", "cron_create",
]

_READ_ONLY = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|DESC|WITH|EXPLAIN)\b", re.IGNORECASE)
_SQL_TOOLS = {"SQL", "sql_execute", "snowflake_sql_execute"}


def is_read_only_sql(sql: str) -> bool:
    body = (sql or "").strip().rstrip(";").strip()
    return bool(body) and ";" not in body and bool(_READ_ONLY.match(body))


class ReadOnlyPolicy:
    def __init__(self) -> None:
        self.denials: list[dict[str, str]] = []

    async def can_use_tool(self, tool: str, tool_input: dict[str, Any], context: Any):
        # Permission checks arrive as tool "SQL" with {action, resource}; the model calls sql_execute.
        sql = tool_input.get("resource") or tool_input.get("sql") or ""
        if tool in _SQL_TOOLS and is_read_only_sql(sql):
            return PermissionResultAllow()
        detail = sql or tool_input.get("command") or tool_input.get("file_path") or str(tool_input)[:200]
        self.denials.append({"tool": tool, "detail": str(detail)[:500]})
        return PermissionResultDeny(
            message="This worker is read-only: only a single SELECT, SHOW, or DESCRIBE statement is allowed."
        )
