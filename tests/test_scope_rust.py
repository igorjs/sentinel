# tests/test_scope_rust.py
from pathlib import Path

import pytest

from scripts.osv import from_fixture
from scripts.scope_rust import detect, plan


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "Cargo.lock").write_text(
        (fixtures_dir / "cargo_lock_with_tokio.lock").read_text()
    )
    return tmp_path


def test_detect_finds_fixable_advisory(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    drifts = detect(workdir, osv)
    assert len(drifts) == 1
    assert drifts[0].scope == "rust"
    assert drifts[0].key == "RUSTSEC-2024-9999"
    assert drifts[0].fixed_versions == ["1.32.0"]
    assert drifts[0].current == "1.30.0"


def test_plan_emits_cargo_update_command(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift)
    assert ["cargo", "update", "-p", "tokio", "--precise", "1.32.0"] in p.commands


def test_plan_cleans_osv_scanner_toml(workdir: Path, fixtures_dir: Path):
    (workdir / "osv-scanner.toml").write_text(
        (fixtures_dir / "osv_scanner_with_tokio.toml").read_text()
    )
    osv = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift)
    for step in p.post_steps:
        step()
    assert "RUSTSEC-2024-9999" not in (workdir / "osv-scanner.toml").read_text()


def test_plan_cleans_deny_toml(workdir: Path, fixtures_dir: Path):
    (workdir / "deny.toml").write_text(
        (fixtures_dir / "deny_with_tokio.toml").read_text()
    )
    osv = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift)
    for step in p.post_steps:
        step()
    assert "RUSTSEC-2024-9999" not in (workdir / "deny.toml").read_text()
