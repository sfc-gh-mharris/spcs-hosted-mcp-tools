import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

PUBLIC_TEST_HOST = "ingress.example.snowflakecomputing.app"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def server_ports(tmp_path_factory):
    """Launch the real server (both listeners) as a subprocess, the same way the container does."""
    port, public_port = _free_port(), _free_port()
    log_path = tmp_path_factory.mktemp("server") / "server.log"
    env = {
        **os.environ,
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "PUBLIC_PORT": str(public_port),
        "MCP_PUBLIC_ALLOWED_HOSTS": f"localhost:*,127.0.0.1:*,{PUBLIC_TEST_HOST}",
    }
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_server"], env=env, stdout=log_file, stderr=subprocess.STDOUT
        )
    deadline = time.monotonic() + 15
    pending = {port, public_port}
    while pending:
        for p in list(pending):
            try:
                if httpx.get(f"http://127.0.0.1:{p}/healthz", timeout=1).status_code == 200:
                    pending.discard(p)
            except httpx.TransportError:
                pass
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            pytest.fail(f"server did not become healthy; log:\n{log_path.read_text()}")
        time.sleep(0.1)
    yield port, public_port
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(server_ports):
    return f"http://127.0.0.1:{server_ports[0]}"


@pytest.fixture(scope="session")
def mcp_url(base_url):
    return f"{base_url}/mcp"


@pytest.fixture(scope="session")
def public_base_url(server_ports):
    return f"http://127.0.0.1:{server_ports[1]}"


@pytest.fixture(scope="session")
def public_mcp_url(public_base_url):
    return f"{public_base_url}/mcp"
