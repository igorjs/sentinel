from pathlib import Path

import pytest

from scripts.target_yaml_env_var import read_value, write_value


@pytest.fixture
def workflow(tmp_path: Path, fixtures_dir: Path) -> Path:
    p = tmp_path / "release.yml"
    p.write_text((fixtures_dir / "workflow_with_env_var.yml").read_text())
    return p


def test_read_top_level_env_var(workflow: Path):
    assert read_value(workflow, "LIBKRUN_BOTTLE_VERSION") == "0.18.1"


def test_read_missing_var_returns_none(workflow: Path):
    assert read_value(workflow, "NONEXISTENT") is None


def test_write_updates_only_target_var(workflow: Path):
    write_value(workflow, "LIBKRUN_BOTTLE_VERSION", "0.19.0")
    text = workflow.read_text()
    assert "0.19.0" in text
    assert "OTHER_VAR" in text
    assert "name: release" in text


def test_write_at_job_level(tmp_path: Path):
    p = tmp_path / "wf.yml"
    p.write_text('jobs:\n  publish:\n    env:\n      MYVAR: "a"\n    runs-on: x\n')
    write_value(p, "MYVAR", "b", env_path="jobs.publish.env")
    assert '"b"' in p.read_text() or "MYVAR: b" in p.read_text()
