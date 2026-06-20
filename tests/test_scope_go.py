from pathlib import Path

import pytest

from scripts.osv import from_fixture
from scripts.scope_go import (
    detect_module_drifts,
    detect_runtime_drift,
    plan_module,
    plan_runtime,
)


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "go.mod").write_text(
        (fixtures_dir / "go_mod_1_24_4.mod").read_text()
    )
    return tmp_path


def test_detect_module_drifts_finds_dep(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_deps.json")
    drifts = detect_module_drifts(workdir, osv, workdir / "go.mod")
    assert len(drifts) == 1
    assert drifts[0].raw["module"] == "google.golang.org/grpc"
    assert "1.80.0" in drifts[0].fixed_versions


def test_detect_module_drifts_skips_stdlib(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_stdlib.json")
    assert detect_module_drifts(workdir, osv, workdir / "go.mod") == []


def test_detect_runtime_drift_finds_stdlib(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_stdlib.json")
    drift = detect_runtime_drift(workdir, osv, workdir / "go.mod")
    assert drift is not None
    assert drift.raw["target"] == "1.25.11"
    assert drift.current == "1.24.4"


def test_detect_runtime_drift_none_when_no_stdlib(
    workdir: Path, fixtures_dir: Path
):
    osv = from_fixture(fixtures_dir / "osv_go_deps.json")
    assert detect_runtime_drift(workdir, osv, workdir / "go.mod") is None


def test_plan_module_emits_go_get(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_deps.json")
    drift = detect_module_drifts(workdir, osv, workdir / "go.mod")[0]
    p = plan_module(workdir, drift, workdir / "go.mod")
    assert ["go", "get", "google.golang.org/grpc@1.80.0"] in p.commands
    assert ["go", "mod", "tidy"] in p.commands


def test_plan_runtime_edits_directive(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_stdlib.json")
    drift = detect_runtime_drift(workdir, osv, workdir / "go.mod")
    p = plan_runtime(workdir, drift, workdir / "go.mod")
    for step in p.post_steps:
        step()
    assert "go 1.25.11" in (workdir / "go.mod").read_text()
    assert "go 1.24.4" not in (workdir / "go.mod").read_text()
