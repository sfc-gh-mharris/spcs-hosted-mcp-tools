import pytest

from coco_worker.policy import DISALLOWED_TOOLS, ReadOnlyPolicy, is_read_only_sql

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("sql", [
    "SHOW TABLES IN SCHEMA MCP_SPCS_DEMO.APP",
    "  select count(*) from t",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "DESCRIBE TABLE t",
    "DESC VIEW v",
    "SELECT 1;",
])
def test_read_only_statements_are_allowed(sql):
    assert is_read_only_sql(sql)


@pytest.mark.parametrize("sql", [
    "DROP TABLE t",
    "CREATE TABLE t (a int)",
    "INSERT INTO t VALUES (1)",
    "SHOW TABLES; DROP TABLE t",
    "GRANT ROLE x TO USER y",
    "CALL some_proc()",
    "",
])
def test_writes_and_multi_statement_sql_are_denied(sql):
    assert not is_read_only_sql(sql)


async def test_policy_allows_read_only_sql_in_both_shapes_the_cli_uses():
    policy = ReadOnlyPolicy()
    # Permission checks arrive as tool "SQL" with {action, resource}; the model-facing tool is sql_execute.
    allowed = await policy.can_use_tool("SQL", {"action": "execute_command", "resource": "SHOW VIEWS IN SCHEMA S"}, None)
    also_allowed = await policy.can_use_tool("sql_execute", {"sql": "SELECT 1"}, None)
    assert allowed.behavior == "allow" and also_allowed.behavior == "allow"
    assert policy.denials == []


async def test_policy_denies_and_records_everything_else():
    policy = ReadOnlyPolicy()
    denied_sql = await policy.can_use_tool("SQL", {"resource": "DROP TABLE t"}, None)
    denied_bash = await policy.can_use_tool("bash", {"command": "rm -rf /"}, None)
    denied_write = await policy.can_use_tool("write", {"file_path": "/x"}, None)
    assert {denied_sql.behavior, denied_bash.behavior, denied_write.behavior} == {"deny"}
    assert "read-only" in denied_sql.message.lower()
    assert [d["tool"] for d in policy.denials] == ["SQL", "bash", "write"]
    assert policy.denials[0]["detail"] == "DROP TABLE t"


def test_interactive_and_side_effect_tools_are_removed_up_front():
    for tool in ("ask_user_question", "bash", "write", "edit", "web_search", "web_fetch", "skill"):
        assert tool in DISALLOWED_TOOLS
    assert "sql_execute" not in DISALLOWED_TOOLS
