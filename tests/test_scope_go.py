from pathlib import Path

import pytest

from scripts.osv import OsvCache, from_fixture
from scripts.scope_go import (
    detect_module_drifts,
    detect_runtime_drift,
    plan_module,
    plan_runtime,
)
from scripts.types import Drift


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "go.mod").write_text((fixtures_dir / "go_mod_1_24_4.mod").read_text())
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


def test_detect_runtime_drift_none_when_no_stdlib(workdir: Path, fixtures_dir: Path):
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


def test_module_drift_sets_severity(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_deps.json")
    drifts = detect_module_drifts(workdir, osv, workdir / "go.mod")
    # Fixture carries no severity data → unknown (fail-open).
    assert drifts[0].severity == "unknown"


def _stdlib_adv(adv_id, fixed, vector):
    return {
        "id": adv_id,
        "summary": "s",
        "severity": [{"type": "CVSS_V3", "score": vector}],
        "affected": [
            {
                "package": {"name": "stdlib"},
                "ranges": [{"events": [{"introduced": "0"}, {"fixed": fixed}]}],
            }
        ],
    }


def test_runtime_drift_severity_is_max_of_contributors(workdir: Path):
    # Two stdlib advisories at different severities (low + high) → runtime drift
    # takes the MAX. go.mod fixture is `go 1.24.4`, so both fixes are >= current.
    osv = OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "Go", "name": "stdlib"},
                            "vulnerabilities": [
                                _stdlib_adv(
                                    "GO-LOW",
                                    "1.24.5",
                                    "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L",  # 3.7 low
                                ),
                                _stdlib_adv(
                                    "GO-HIGH",
                                    "1.25.0",
                                    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H",  # 7.5 high
                                ),
                            ],
                        }
                    ]
                }
            ]
        }
    )
    drift = detect_runtime_drift(workdir, osv, workdir / "go.mod")
    assert drift is not None
    assert drift.severity == "high"  # max(low, high)
    assert drift.raw["target"] == "1.25.0"  # max fixed version


def test_plan_module_cleans_osv_scanner_toml(workdir: Path):
    (workdir / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "GO-X"\n')
    drift = Drift(
        scope="go",
        key="GO-X",
        summary="s",
        fixed_versions=["1.2.3"],
        current="",
        raw={"module": "example.com/m"},
    )
    p = plan_module(workdir, drift, workdir / "go.mod")
    for step in p.post_steps:
        step()
    assert "GO-X" not in (workdir / "osv-scanner.toml").read_text()
