"""prepare_cli_home: give the CLI a writable SNOWFLAKE_HOME that still sees SPCS's connections.toml."""

from coco_worker.cli_home import prepare_cli_home

TOML = '[default]\naccount = "A"\nauthenticator = "OAUTH"\ntoken_file_path = "/snowflake/session/token"\n'


def test_copies_the_generated_connection_into_a_writable_home(tmp_path):
    spcs_home = tmp_path / "snowflake-home"
    spcs_home.mkdir()
    (spcs_home / "connections.toml").write_text(TOML)
    writable = tmp_path / "home" / ".snowflake"

    env = prepare_cli_home({"SNOWFLAKE_HOME": str(spcs_home), "HOME": str(tmp_path / "home")}, writable)

    assert env == {"SNOWFLAKE_HOME": str(writable)}
    copied = writable / "connections.toml"
    assert copied.read_text() == TOML
    # The CLI warns about, or refuses, group/world-readable connection files.
    assert oct(copied.stat().st_mode & 0o777) == "0o600"
    assert (writable / "cortex").is_dir()


def test_does_nothing_outside_spcs(tmp_path):
    assert prepare_cli_home({"HOME": str(tmp_path)}, tmp_path / ".snowflake") == {}


def test_does_nothing_when_snowflake_home_has_no_connections_file(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert prepare_cli_home({"SNOWFLAKE_HOME": str(empty)}, tmp_path / ".snowflake") == {}
