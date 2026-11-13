import pytest

from mcp_server.tools import add


def test_add_integers():
    assert add(2, 3) == 5


def test_add_negative_and_float():
    assert add(-1.5, 1.5) == 0


def test_add_float_precision():
    assert add(0.1, 0.2) == pytest.approx(0.3)


def test_add_large_ints():
    assert add(10**15, 1) == 1_000_000_000_000_001
