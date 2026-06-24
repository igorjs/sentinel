import io
import json as _json
import urllib.error
from datetime import date

import pytest

from scripts import runtime_eol as rt
from scripts.runtime_eol import (
    RuntimeEolError,
    bump_floor,
    bump_pin,
    eol_target,
    fetch_cycles,
    floor_lower_cycle,
    pin_cycle,
)


def test_floor_lower_cycle_python():
    assert floor_lower_cycle(">=3.8", parts=2) == "3.8"
    assert floor_lower_cycle(">=3.8,<4.0", parts=2) == "3.8"
    assert floor_lower_cycle(">=3.8.1", parts=2) == "3.8"


def test_floor_lower_cycle_node():
    assert floor_lower_cycle(">=18", parts=1) == "18"
    assert floor_lower_cycle(">=18.0.0", parts=1) == "18"


def test_floor_lower_cycle_unparseable():
    assert floor_lower_cycle("^18 || ^20", parts=1) is None
    assert floor_lower_cycle("18.x", parts=1) is None
    assert floor_lower_cycle("", parts=2) is None


def test_bump_floor_preserves_upper_bound():
    assert bump_floor(">=3.8,<4.0", "3.9") == ">=3.9,<4.0"
    assert bump_floor(">=18", "20") == ">=20"
    assert bump_floor(">= 3.8", "3.9") == ">= 3.9"


def test_pin_cycle():
    assert pin_cycle("3.8.10", parts=2) == "3.8"
    assert pin_cycle("3.8", parts=2) == "3.8"
    assert pin_cycle("v18", parts=1) == "18"
    assert pin_cycle("18.16.0", parts=1) == "18"
    assert pin_cycle("lts/iron", parts=1) is None


def test_bump_pin_matches_granularity():
    # python cycle granularity = 2 components
    assert bump_pin("3.8", "3.9", "3.9.18", parts=2) == "3.9"
    assert bump_pin("3.8.10", "3.9", "3.9.18", parts=2) == "3.9.18"
    # node cycle granularity = 1 component
    assert bump_pin("18", "20", "20.11.1", parts=1) == "20"
    assert bump_pin("18.16.0", "20", "20.11.1", parts=1) == "20.11.1"
    assert bump_pin("v18", "20", "20.11.1", parts=1) == "v20"
    assert bump_pin("v18.16.0", "20", "20.11.1", parts=1) == "v20.11.1"


PY = [
    {"cycle": "3.13", "eol": "2029-10-31", "latest": "3.13.1", "lts": False},
    {"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.7", "lts": False},
    {"cycle": "3.9", "eol": "2025-10-31", "latest": "3.9.20", "lts": False},
    {"cycle": "3.8", "eol": "2024-10-07", "latest": "3.8.20", "lts": False},
    {"cycle": "2.7", "eol": True, "latest": "2.7.18", "lts": False},
]
NODE = [
    {"cycle": "22", "eol": "2027-04-30", "latest": "22.1.0", "lts": "2024-10-29"},
    {"cycle": "21", "eol": "2024-06-01", "latest": "21.7.3", "lts": False},
    {"cycle": "20", "eol": "2026-04-30", "latest": "20.11.1", "lts": "2023-10-24"},
    {"cycle": "18", "eol": "2025-04-30", "latest": "18.20.1", "lts": "2022-10-25"},
]
TODAY = date(2026, 1, 1)


def test_eol_target_python_in_window():
    # 3.8 already EOL -> oldest supported newer cycle (3.9 is also EOL by date, so skip to 3.12)
    assert eol_target(PY, "3.8", today=TODAY, lead_days=30, lts_only=False) == ("3.12", "3.12.7")


def test_eol_target_python_not_in_window():
    # 3.12 eol 2028 -> far away -> no bump
    assert eol_target(PY, "3.12", today=TODAY, lead_days=30, lts_only=False) is None


def test_eol_target_lead_window_brings_it_forward():
    # 3.9 eol 2025-10-31; today 2025-10-15 with 30d lead -> in window
    near = date(2025, 10, 15)
    assert eol_target(PY, "3.9", today=near, lead_days=30, lts_only=False) == ("3.12", "3.12.7")


def test_eol_target_lead_zero_fires_on_eol_date():
    on_eol = date(2024, 10, 7)
    assert eol_target(PY, "3.8", today=on_eol, lead_days=0, lts_only=False) == ("3.9", "3.9.20")
    day_before = date(2024, 10, 6)
    assert eol_target(PY, "3.8", today=day_before, lead_days=0, lts_only=False) is None


def test_eol_target_node_skips_odd_nonlts():
    # 18 in window (eol 2025-04-30 < 2026); target must be 20 (LTS even), not 21
    assert eol_target(NODE, "18", today=TODAY, lead_days=30, lts_only=True) == ("20", "20.11.1")


def test_eol_target_unknown_current_cycle():
    assert eol_target(PY, "3.99", today=TODAY, lead_days=30, lts_only=False) is None


def test_eol_target_skips_newer_cycle_already_eol_by_date():
    cycles = [
        {"cycle": "3.10", "eol": "2030-01-01", "latest": "3.10.5", "lts": False},
        {"cycle": "3.9", "eol": "2025-10-31", "latest": "3.9.20", "lts": False},  # past date
        {"cycle": "3.8", "eol": "2024-10-07", "latest": "3.8.20", "lts": False},  # current, EOL
    ]
    today = date(2026, 1, 1)
    # 3.9 is already EOL by date -> must NOT be chosen; 3.10 (still supported) is the target
    assert eol_target(cycles, "3.8", today=today, lead_days=30, lts_only=False) == (
        "3.10",
        "3.10.5",
    )


def test_fetch_cycles_parses_json(monkeypatch):
    payload = _json.dumps([{"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.7"}]).encode()

    def fake_urlopen(url, timeout=None):
        assert "python" in url
        return io.BytesIO(payload)

    monkeypatch.setattr(rt.urllib.request, "urlopen", fake_urlopen)
    cycles = fetch_cycles("python")
    assert cycles[0]["cycle"] == "3.12"


def test_fetch_cycles_network_error_raises_typed(monkeypatch):
    def boom(url, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(rt.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeEolError):
        fetch_cycles("nodejs")


def test_fetch_cycles_bad_json_raises_typed(monkeypatch):
    monkeypatch.setattr(
        rt.urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(b"not json")
    )
    with pytest.raises(RuntimeEolError):
        fetch_cycles("python")
