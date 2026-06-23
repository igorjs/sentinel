from pathlib import Path

import pytest

from scripts import osv as osv_mod
from scripts.osv import OsvCache, from_fixture


def test_empty_fixture_no_advisories(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_empty.json")
    assert cache.advisories("crates.io") == []
    assert cache.fixable_advisories("crates.io") == []


def test_cargo_fixture_finds_advisory(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    advs = cache.advisories("crates.io")
    assert len(advs) == 1
    assert advs[0]["id"] == "RUSTSEC-2024-9999"


def test_cargo_fixture_advisory_is_fixable(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    fixable = cache.fixable_advisories("crates.io")
    assert len(fixable) == 1


def test_filter_by_package(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    assert len(cache.advisories("crates.io", package="tokio")) == 1
    assert cache.advisories("crates.io", package="other") == []


def test_scan_missing_binary_raises_clear_error(tmp_path: Path, monkeypatch):
    def _raise(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "osv-scanner")

    monkeypatch.setattr(osv_mod.subprocess, "run", _raise)
    with pytest.raises(RuntimeError, match="osv-scanner not found"):
        OsvCache.scan(tmp_path)
