"""Entrypoint: python -m coco_worker.

Reads HOST, PORT, COCO_CONNECTION (default "default", the connection SPCS writes when
sessionTokenConfig.mountConnectionConfig is true), COCO_MODEL, COCO_MAX_SECONDS,
CORTEX_CODE_CLI_PATH, COCO_WORKDIR, LOG_LEVEL.
"""

import logging
import os
from pathlib import Path

import uvicorn

from coco_worker.app import create_app
from coco_worker.cli_home import prepare_cli_home
from coco_worker.runner import RunSettings


def main() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    workdir = os.environ.get("COCO_WORKDIR", "/tmp/coco-work")
    os.makedirs(workdir, exist_ok=True)
    settings = RunSettings(
        connection=os.environ.get("COCO_CONNECTION", "default"),
        model=os.environ.get("COCO_MODEL", "claude-sonnet-5"),
        cli_path=os.environ.get("CORTEX_CODE_CLI_PATH"),
        workdir=workdir,
        max_seconds=int(os.environ.get("COCO_MAX_SECONDS", "300")),
        cli_env=prepare_cli_home(os.environ, Path.home() / ".snowflake"),
    )
    logging.getLogger("coco_worker").info("cli env overrides: %s", settings.cli_env or "none")
    uvicorn.run(create_app(settings), host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")),
                log_level=level.lower())


if __name__ == "__main__":
    main()
