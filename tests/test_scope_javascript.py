from pathlib import Path

import pytest

from scripts.config import Config
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
