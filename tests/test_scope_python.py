from pathlib import Path

import pytest

from scripts.config import Config
from scripts.osv import OsvCache, from_fixture
from scripts.scope_python import detect, detect_pkg_manager, plan, run
from scripts.scope_python import run as py_run


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text((fixtures_dir / "pyproject_toml.toml").read_text())
    return tmp_path


def test_detect_pkg_manager_poetry(workdir: Path):
    (workdir / "poetry.lock").write_text("")
    assert detect_pkg_manager(workdir) == "poetry"


def test_detect_pkg_manager_uv(workdir: Path):
    (workdir / "uv.lock").write_text("")
    assert detect_pkg_manager(workdir) == "uv"


def test_detect_pkg_manager_pipenv(workdir: Path):
    (workdir / "Pipfile.lock").write_text("")
    assert detect_pkg_manager(workdir) == "pipenv"


def test_detect_pkg_manager_pyproject_only(workdir: Path):
    # pyproject.toml exists (set up by `workdir` fixture), no lockfile
    assert detect_pkg_manager(workdir) == "pyproject"


def test_detect_pkg_manager_none(tmp_path: Path):
    # neither pyproject nor lockfile
    assert detect_pkg_manager(tmp_path) is None


def test_detect_finds_pypi_advisory(workdir: Path, fixtures_dir: Path):
    (workdir / "uv.lock").write_text("")
    osv = from_fixture(fixtures_dir / "osv_pypi_fixable.json")
    drifts = detect(workdir, osv)
    assert len(drifts) == 1
    assert drifts[0].raw["module"] == "requests"


def test_plan_poetry_command(workdir: Path, fixtures_dir: Path):
    (workdir / "poetry.lock").write_text("")
    osv = from_fixture(fixtures_dir / "osv_pypi_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift, "poetry")
    assert ["poetry", "update", "requests"] in p.commands


def test_plan_uv_command(workdir: Path, fixtures_dir: Path):
    (workdir / "uv.lock").write_text("")
    osv = from_fixture(fixtures_dir / "osv_pypi_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift, "uv")
    assert ["uv", "lock", "--upgrade-package", "requests"] in p.commands


def test_plan_pipenv_command(workdir: Path, fixtures_dir: Path):
    (workdir / "Pipfile.lock").write_text("")
    osv = from_fixture(fixtures_dir / "osv_pypi_fixable.json")
    drift = detect(workdir, osv)[0]
    p = plan(workdir, drift, "pipenv")
    assert ["pipenv", "update", "requests"] in p.commands


def test_plan_pyproject_edits_in_place(tmp_path: Path, fixtures_dir: Path):
    (tmp_path / "pyproject.toml").write_text(
        (fixtures_dir / "pyproject_pep621_pinned.toml").read_text()
    )
    osv = from_fixture(fixtures_dir / "osv_pypi_fixable.json")
    drift = detect(tmp_path, osv)[0]
    p = plan(tmp_path, drift, "pyproject")
    assert p.commands == []  # pyproject path uses post_steps, not commands
    for step in p.post_steps:
        step()
    text = (tmp_path / "pyproject.toml").read_text()
    assert "requests==2.32.0" in text
    assert "requests==2.28.0" not in text
    # untouched dep preserved
    assert "click>=8.0" in text


def _osv_requests(vector):
    return OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "PyPI", "name": "requests"},
                            "vulnerabilities": [
                                {
                                    "id": "PYSEC-1",
                                    "summary": "s",
                                    "severity": [{"type": "CVSS_V3", "score": vector}],
                                    "affected": [
                                        {
                                            "package": {"name": "requests"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "2.32.0"},
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
    (workdir / "uv.lock").write_text("")
    osv = _osv_requests("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L")  # 3.7 low
    cfg = Config()
    cfg.defaults.min_severity = "high"
    results = py_run(workdir, cfg, osv, dry_run=True)
    assert results == []
    assert "skipped 1" in capsys.readouterr().out


def test_run_pyproject_missing_dependencies_key_returns_issue(tmp_path: Path, fixtures_dir: Path):
    """run() must not crash when pyproject.toml has no [project.dependencies].

    _edit_pyproject_pep621() raises KeyError in that case; the except clause
    in run() must catch it and fall back to an issue Result.
    """
    from unittest.mock import patch

    # pyproject.toml with [project] but NO dependencies key
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"\nversion = "0.1.0"\n')
    osv = from_fixture(fixtures_dir / "osv_pypi_fixable.json")

    # Patch apply_plan to raise KeyError, simulating what happens when
    # _edit_pyproject_pep621 encounters a missing [project.dependencies].
    with patch(
        "scripts.scope_python.apply_plan", side_effect=KeyError("[project.dependencies] not found")
    ):
        results = run(tmp_path, Config(), osv, dry_run=True)

    assert len(results) == 1
    result = results[0]
    # Issue fallback in dry_run returns kind="noop"; summary must mention
    # "blocked" confirming the KeyError handler was reached, not a clean path.
    assert result.kind == "noop"
    assert "blocked" in result.summary
