from pathlib import Path

import pytest

from scripts.osv import from_fixture
from scripts.scope_python import detect, detect_pkg_manager, plan


@pytest.fixture
def workdir(tmp_path: Path, fixtures_dir: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        (fixtures_dir / "pyproject_toml.toml").read_text()
    )
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
    assert 'click>=8.0' in text
