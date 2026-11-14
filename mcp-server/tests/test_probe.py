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


def test_probe_checks_an_extra_tool_against_expectations(mcp_url):
    proc = _probe(mcp_url, "--tool", "add", "--args", '{"a": 1.5, "b": 2}', "--expect", "result=3.5")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS tool add" in proc.stdout


def test_probe_fails_when_expectation_does_not_match(mcp_url):
    proc = _probe(mcp_url, "--tool", "add", "--args", '{"a": 1, "b": 2}', "--expect", "result=4")
    assert proc.returncode == 1
    assert "FAIL expect result=4" in proc.stdout


def test_probe_supports_contains_expectations(mcp_url):
    proc = _probe(mcp_url, "--tool", "add", "--args", '{"a": 40, "b": 2}', "--expect", "result~=42")
    assert proc.returncode == 0, proc.stdout + proc.stderr
