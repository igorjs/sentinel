# tests/test_scope_rust.py
from pathlib import Path

import pytest

from scripts.config import Config
from scripts.osv import OsvCache, from_fixture
from scripts.scope_rust import detect, plan, run


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "Cargo.lock").write_text((fixtures_dir / "cargo_lock_with_tokio.lock").read_text())
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
    (workdir / "deny.toml").write_text((fixtures_dir / "deny_with_tokio.toml").read_text())
    osv = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift)
    for step in p.post_steps:
        step()
    assert "RUSTSEC-2024-9999" not in (workdir / "deny.toml").read_text()


def _cargo_lock(tmp_path):
    (tmp_path / "Cargo.lock").write_text('[[package]]\nname = "tokio"\nversion = "1.30.0"\n')


def _osv_with_severity(vector):
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "crates.io", "name": "tokio"},
                            "vulnerabilities": [
                                {
                                    "id": "RUSTSEC-2024-1",
                                    "summary": "s",
                                    "severity": [{"type": "CVSS_V3", "score": vector}],
                                    "affected": [
                                        {
                                            "package": {"name": "tokio"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "1.32.0"},
                                                    ]
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )


def test_detect_sets_severity_band(tmp_path):
    _cargo_lock(tmp_path)
    osv = _osv_with_severity("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")  # 9.8 critical
    drift = detect(tmp_path, osv)[0]
    assert drift.severity == "critical"


def test_run_skips_below_threshold(tmp_path, capsys):
    _cargo_lock(tmp_path)
    osv = _osv_with_severity("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L")  # 3.7 low
    cfg = Config()
    cfg.defaults.min_severity = "high"
    results = run(tmp_path, cfg, osv, dry_run=True)
    assert results == []  # low < high → skipped
    assert "skipped 1" in capsys.readouterr().out


def test_run_acts_when_at_threshold(tmp_path):
    _cargo_lock(tmp_path)
    osv = _osv_with_severity("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")  # critical
    cfg = Config()
    cfg.defaults.min_severity = "high"
    results = run(tmp_path, cfg, osv, dry_run=True)
    assert len(results) == 1


def _osv_v2_groups(max_severity):
    # osv-scanner v2.4.0 shape: severity lives only in package.groups[].max_severity,
    # never in a per-vuln severity[] array.
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "crates.io", "name": "tokio"},
                            "groups": [{"ids": ["RUSTSEC-2024-1"], "max_severity": max_severity}],
                            "vulnerabilities": [
                                {
                                    "id": "RUSTSEC-2024-1",
                                    "summary": "s",
                                    "affected": [
                                        {
                                            "package": {"name": "tokio"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "1.32.0"},
                                                    ]
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )


def test_detect_severity_from_v2_groups(tmp_path):
    _cargo_lock(tmp_path)
    drift = detect(tmp_path, _osv_v2_groups("9.8"))[0]
    assert drift.severity == "critical"  # resolved from groups[].max_severity


def test_run_skips_below_threshold_v2_groups(tmp_path, capsys):
    _cargo_lock(tmp_path)
    cfg = Config()
    cfg.defaults.min_severity = "high"
    results = run(tmp_path, cfg, _osv_v2_groups("3.7"), dry_run=True)  # low < high
    assert results == []
    assert "skipped 1" in capsys.readouterr().out


def _osv_no_severity():
    # Advisory with no severity data → derive_severity → "unknown".
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "crates.io", "name": "tokio"},
                            "vulnerabilities": [
                                {
                                    "id": "RUSTSEC-2024-2",
                                    "summary": "s",
                                    "affected": [
                                        {
                                            "package": {"name": "tokio"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "1.32.0"},
                                                    ]
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )


def test_run_acts_on_unknown_severity_fail_open(tmp_path, capsys):
    # Fail-open at the run layer: an unscored advisory is bumped even under a
    # strict threshold, and is not counted as skipped.
    _cargo_lock(tmp_path)
    cfg = Config()
    cfg.defaults.min_severity = "critical"
    results = run(tmp_path, cfg, _osv_no_severity(), dry_run=True)
    assert len(results) == 1
    assert "skipped" not in capsys.readouterr().out


def _osv_two_crates_one_advisory():
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "crates.io", "name": "crate-a"},
                            "vulnerabilities": [
                                {
                                    "id": "RUSTSEC-2024-MULTI",
                                    "summary": "s",
                                    "affected": [
                                        {
                                            "package": {"name": "crate-a"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "1.1.0"},
                                                    ]
                                                }
                                            ],
                                        },
                                        {
                                            "package": {"name": "crate-b"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "2.2.0"},
                                                    ]
                                                }
                                            ],
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )


def test_run_dedups_suppression_cleanup_across_siblings(tmp_path, capsys):
    # One advisory affecting two crates → two PRs, but only ONE strips the
    # shared osv-scanner.toml suppression (no redundant/competing ignore edits).
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "crate-a"\nversion = "1.0.0"\n\n'
        '[[package]]\nname = "crate-b"\nversion = "2.0.0"\n'
    )
    (tmp_path / "osv-scanner.toml").write_text(
        '[[IgnoredVulns]]\nid = "RUSTSEC-2024-MULTI"\nreason = "x"\n'
    )
    drifts = detect(tmp_path, _osv_two_crates_one_advisory())
    assert len(drifts) == 2  # both crates detected
    run(tmp_path, Config(), _osv_two_crates_one_advisory(), dry_run=True)
    out = capsys.readouterr().out
    assert out.count("clean_osv-scanner.toml") == 1


def test_plan_clean_suppressions_false_skips_cleanup(tmp_path):
    (tmp_path / "Cargo.lock").write_text('[[package]]\nname = "crate-a"\nversion = "1.0.0"\n')
    (tmp_path / "osv-scanner.toml").write_text(
        '[[IgnoredVulns]]\nid = "RUSTSEC-2024-MULTI"\nreason = "x"\n'
    )
    drift = detect(tmp_path, _osv_two_crates_one_advisory())[0]
    assert plan(tmp_path, drift, clean_suppressions=True).post_steps  # default cleans
    assert plan(tmp_path, drift, clean_suppressions=False).post_steps == ()
