import os
import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    """Launch the real server as a subprocess, the same way the container does."""
    port = _free_port()
    log_path = tmp_path_factory.mktemp("server") / "server.log"
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port)}
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_server"], env=env, stdout=log_file, stderr=subprocess.STDOUT
        )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while True:
        try:
            if httpx.get(f"{url}/healthz", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            pass
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            pytest.fail(f"server did not become healthy; log:\n{log_path.read_text()}")
        time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def mcp_url(base_url):
    return f"{base_url}/mcp"
