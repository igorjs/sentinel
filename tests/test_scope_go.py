import subprocess
from pathlib import Path

import pytest

from scripts.models import Drift
from scripts.osv import OsvCache, from_fixture
from scripts.scope_go import (
    detect_module_drifts,
    detect_runtime_drift,
    plan_module,
    plan_runtime,
)
from scripts.validate import UnsafeIdentifier


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
    # Fixture carries no severity data -> unknown (fail-open).
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
    # Two stdlib advisories at different severities (low + high) -> runtime drift
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


def test_plan_runtime_rejects_unsafe_target(workdir: Path):
    drift = Drift(
        scope="go",
        key="runtime-x",
        summary="s",
        fixed_versions=["1.25.0 ; evil"],
        current="1.24.4",
        raw={"advisory_ids": ["GO-X"], "target": "1.25.0 ; evil"},
    )
    with pytest.raises(UnsafeIdentifier):
        plan_runtime(workdir, drift, workdir / "go.mod")


def test_plan_runtime_branch_goes_through_branch_name(workdir: Path, fixtures_dir: Path):
    osv = from_fixture(fixtures_dir / "osv_go_stdlib.json")
    drift = detect_runtime_drift(workdir, osv, workdir / "go.mod")
    p = plan_runtime(workdir, drift, workdir / "go.mod")
    assert p.branch.startswith("sentinel/go/")
    assert p.branch != "sentinel/go/runtime-1.25.11"  # hashed, not the raw f-string


def test_run_routes_unsafe_runtime_target_to_issue(workdir: Path, monkeypatch):
    # run()'s runtime path must open an issue (not crash) on an unsafe target,
    # mirroring the module path and the gh-release-pin run() fallback.
    import scripts.scope_go as go_mod
    from scripts.config import Config

    unsafe = Drift(
        scope="go",
        key="runtime-x",
        summary="s",
        fixed_versions=["1.25.0 ; evil"],
        current="1.24.4",
        severity="high",
        raw={"advisory_ids": ["GO-X"], "target": "1.25.0 ; evil"},
    )
    monkeypatch.setattr(go_mod, "detect_module_drifts", lambda *a, **k: [])
    monkeypatch.setattr(go_mod, "detect_runtime_drift", lambda *a, **k: unsafe)
    results = go_mod.run(workdir, Config(), OsvCache({"results": []}), dry_run=True)
    assert len(results) == 1
    assert results[0].kind == "noop"
    assert "unsafe" in results[0].summary.lower()


def test_run_routes_symlink_escape_gomod_to_issue(tmp_path: Path):
    # A go.mod symlink escaping the workspace passes the load reject (relative
    # path) but must be caught at the use site and open an issue, not crash.
    import scripts.scope_go as go_mod
    from scripts.config import Config

    outside = tmp_path / "outside.mod"
    outside.write_text("module x\ngo 1.24.4\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / "go.mod").symlink_to(outside)
    results = go_mod.run(work, Config(), OsvCache({"results": []}), dry_run=True)
    assert len(results) == 1
    assert results[0].kind == "noop"
    assert "unsafe" in results[0].summary.lower()


def test_run_routes_runtime_apply_failure_to_issue(workdir: Path, monkeypatch):
    import scripts.scope_go as go_mod
    from scripts.config import Config

    drift = Drift(
        scope="go",
        key="runtime-x",
        summary="s",
        fixed_versions=["1.25.11"],
        current="1.24.4",
        severity="high",
        raw={"advisory_ids": ["GO-X"], "target": "1.25.11"},
    )
    monkeypatch.setattr(go_mod, "detect_module_drifts", lambda *a, **k: [])
    monkeypatch.setattr(go_mod, "detect_runtime_drift", lambda *a, **k: drift)

    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, ["git", "push"])

    monkeypatch.setattr(go_mod, "apply_plan", _boom)
    results = go_mod.run(workdir, Config(), OsvCache({"results": []}), dry_run=True)
    assert len(results) == 1
    assert results[0].kind == "noop"  # dry-run issue
    assert "blocked" in results[0].summary.lower()
