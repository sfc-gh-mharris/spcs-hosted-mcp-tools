"""Make the SPCS-generated connection usable by the cortex CLI.

With sessionTokenConfig.mountConnectionConfig, SPCS writes connections.toml under a read-only
directory and points SNOWFLAKE_HOME at it. The CLI also keeps its own state (conversations,
caches) under SNOWFLAKE_HOME/cortex, so it fails with EACCES creating
/snowflake/home/cortex/conversations. Copying connections.toml into a writable directory and
pointing the CLI's SNOWFLAKE_HOME there fixes that. The copy is safe to take once at startup:
it holds token_file_path, not the token, and SPCS rotates the token file in place.
"""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path


def prepare_cli_home(env: Mapping[str, str], writable_home: Path) -> dict[str, str]:
    """Return environment overrides for the CLI process; empty when not running in SPCS."""
    source_dir = env.get("SNOWFLAKE_HOME")
    if not source_dir:
        return {}
    source = Path(source_dir) / "connections.toml"
    if not source.is_file():
        return {}
    writable_home.mkdir(parents=True, exist_ok=True)
    (writable_home / "cortex").mkdir(exist_ok=True)
    target = writable_home / "connections.toml"
    shutil.copyfile(source, target)
    os.chmod(target, 0o600)
    return {"SNOWFLAKE_HOME": str(writable_home)}
