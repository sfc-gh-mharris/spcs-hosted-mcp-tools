import socket
import subprocess
import sys


def _probe(url: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.probe", "--url", url, *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_probe_exits_zero_against_running_server(mcp_url):
    proc = _probe(mcp_url)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PROBE PASSED" in proc.stdout


def test_probe_exits_nonzero_when_unreachable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
    proc = _probe(f"http://127.0.0.1:{closed_port}/mcp", "--timeout", "5")
    assert proc.returncode == 1
    assert "PROBE FAILED" in proc.stdout
