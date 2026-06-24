# tests/test_integration_runtime_eol.py
"""Hits the real endoflife.date API. Skipped without network/opt-in env."""

import os

import pytest

from scripts.runtime_eol import fetch_cycles

pytestmark = pytest.mark.skipif(
    os.environ.get("SENTINEL_NET_TESTS") != "1", reason="network test (set SENTINEL_NET_TESTS=1)"
)


def test_real_python_cycles_have_expected_shape():
    cycles = fetch_cycles("python")
    assert cycles and all("cycle" in c and "eol" in c for c in cycles)
