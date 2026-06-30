from datetime import date
from pathlib import Path

import pytest

from scripts.config import Config, ScopeOverride
from scripts.models import Drift
from scripts.osv import OsvCache, from_fixture
from scripts.scope_javascript import detect, detect_pkg_manager, plan, run


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "package.json").write_text((fixtures_dir / "package_json.json").read_text())
    return tmp_path


def test_detect_pkg_manager_npm(workdir: Path):
    (workdir / "package-lock.json").write_text("{}")
    assert detect_pkg_manager(workdir) == "npm"


def test_detect_pkg_manager_pnpm(workdir: Path):
    (workdir / "pnpm-lock.yaml").write_text("")
    assert detect_pkg_manager(workdir) == "pnpm"


def test_detect_pkg_manager_yarn(workdir: Path):
    (workdir / "yarn.lock").write_text("")
    assert detect_pkg_manager(workdir) == "yarn"


def test_detect_pkg_manager_none(workdir: Path):
    assert detect_pkg_manager(workdir) is None


def test_detect_finds_npm_advisory(workdir: Path, fixtures_dir: Path):
    (workdir / "package-lock.json").write_text("{}")
    osv = from_fixture(fixtures_dir / "osv_npm_fixable.json")
    drifts = detect(workdir, osv)
    assert len(drifts) == 1
    assert drifts[0].raw["module"] == "lodash"
    assert drifts[0].fixed_versions == ["4.17.21"]


def test_plan_npm_command(workdir: Path, fixtures_dir: Path):
    (workdir / "package-lock.json").write_text("{}")
    osv = from_fixture(fixtures_dir / "osv_npm_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift, "npm")
    assert ["npm", "install", "lodash@4.17.21"] in p.commands


def test_plan_pnpm_command(workdir: Path, fixtures_dir: Path):
    (workdir / "pnpm-lock.yaml").write_text("")
    osv = from_fixture(fixtures_dir / "osv_npm_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift, "pnpm")
    assert ["pnpm", "update", "lodash@4.17.21"] in p.commands


def test_plan_yarn_command(workdir: Path, fixtures_dir: Path):
    (workdir / "yarn.lock").write_text("")
    osv = from_fixture(fixtures_dir / "osv_npm_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift, "yarn")
    assert ["yarn", "upgrade", "lodash@4.17.21"] in p.commands


def _osv_lodash(vector):
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "npm", "name": "lodash"},
                            "vulnerabilities": [
                                {
                                    "id": "GHSA-1",
                                    "summary": "s",
                                    "severity": [{"type": "CVSS_V3", "score": vector}],
                                    "affected": [
                                        {
                                            "package": {"name": "lodash"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "4.17.21"},
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


def test_run_skips_below_threshold(workdir, capsys):
    (workdir / "package-lock.json").write_text("{}")
    osv = _osv_lodash("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L")  # 3.7 low
    cfg = Config()
    cfg.defaults.min_severity = "critical"
    results = run(workdir, cfg, osv, dry_run=True)
    assert results == []
    assert "skipped 1" in capsys.readouterr().out


def test_plan_cleans_osv_scanner_toml(workdir):
    (workdir / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "GHSA-X"\n')
    drift = Drift(
        scope="javascript",
        key="GHSA-X",
        summary="s",
        fixed_versions=["1.2.3"],
        current="",
        raw={"module": "lodash"},
    )
    p = plan(workdir, drift, "npm")
    for step in p.post_steps:
        step()
    assert "GHSA-X" not in (workdir / "osv-scanner.toml").read_text()


def test_plan_no_cleanup_when_disabled(workdir):
    (workdir / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "GHSA-X"\n')
    drift = Drift(
        scope="javascript",
        key="GHSA-X",
        summary="s",
        fixed_versions=["1.2.3"],
        current="",
        raw={"module": "lodash"},
    )
    assert plan(workdir, drift, "npm", clean_suppressions=False).post_steps == ()


def _osv_two_npm_packages_one_advisory():
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "npm", "name": "pkg-a"},
                            "vulnerabilities": [
                                {
                                    "id": "GHSA-MULTI",
                                    "summary": "s",
                                    "affected": [
                                        {
                                            "package": {"name": "pkg-a"},
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
                                            "package": {"name": "pkg-b"},
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


def test_run_dedups_suppression_cleanup_across_siblings(workdir, capsys):
    (workdir / "package-lock.json").write_text("{}")
    (workdir / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "GHSA-MULTI"\n')
    run(workdir, Config(), _osv_two_npm_packages_one_advisory(), dry_run=True)
    assert capsys.readouterr().out.count("clean_osv-scanner.toml") == 1


def _empty_osv():
    return OsvCache({"results": []})


def test_run_opens_runtime_pr_when_opted_in(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text('{\n  "name": "x",\n  "engines": {"node": ">=18"}\n}\n')
    import scripts.runtime as rtmod

    monkeypatch.setattr(rtmod, "_today", lambda: date(2026, 1, 1))
    monkeypatch.setattr(
        rtmod,
        "fetch_cycles",
        lambda _p: [
            {"cycle": "22", "eol": "2027-04-30", "latest": "22.1.0", "lts": "2024-10-29"},
            {"cycle": "21", "eol": "2024-06-01", "latest": "21.7.3", "lts": False},
            {"cycle": "20", "eol": "2026-04-30", "latest": "20.11.1", "lts": "2023-10-24"},
            {"cycle": "18", "eol": "2025-04-30", "latest": "18.20.1", "lts": "2022-10-25"},
        ],
    )
    results = run(
        tmp_path,
        Config(scopes={"javascript": ScopeOverride(update_runtime=True)}),
        _empty_osv(),
        dry_run=True,
    )
    runtime = [r for r in results if r.key == "runtime-eol"]
    assert len(runtime) == 1 and runtime[0].kind == "noop"  # dry-run


def test_run_no_runtime_pr_by_default(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x", "engines": {"node": ">=18"}}')
    results = run(tmp_path, Config(), _empty_osv(), dry_run=True)
    assert [r for r in results if r.key == "runtime-eol"] == []


def test_run_includes_freshness_results(tmp_path, monkeypatch):
    import scripts.scope_javascript as sj
    from scripts.config import Config, ScopeOverride
    from scripts.models import Result

    (tmp_path / "package.json").write_text('{"name":"x"}')

    sentinel = Result(scope="javascript", key="freshness", kind="noop", summary="")
    monkeypatch.setattr(
        sj.freshness, "run", lambda workdir, config, *, dry_run, adapter: [sentinel]
    )
    # no lockfile -> security path is a no-op; freshness result still present
    cfg = Config(scopes={"javascript": ScopeOverride(update_freshness=True)})

    class _Osv:
        def fixable_advisories(self, eco):
            return []

    results = sj.run(tmp_path, cfg, _Osv(), dry_run=True)
    assert sentinel in results
