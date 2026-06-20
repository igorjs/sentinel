# tests/test_scope_gh_release_pin.py
from pathlib import Path

import pytest

from scripts.config import CustomScope
from scripts.scope_gh_release_pin import detect, plan


@pytest.fixture
def workflow(tmp_path: Path, fixtures_dir: Path) -> Path:
    p = tmp_path / ".github" / "workflows" / "release.yml"
    p.parent.mkdir(parents=True)
    p.write_text((fixtures_dir / "workflow_with_env_var.yml").read_text())
    return p


@pytest.fixture
def custom() -> CustomScope:
    return CustomScope(
        name="libkrun-bottle",
        kind="gh-release-pin",
        extra={
            "upstream_repo": "igorjs/libkrun-builds",
            "target_file": ".github/workflows/release.yml",
            "target_kind": "yaml-env-var",
            "env_var": "LIBKRUN_BOTTLE_VERSION",
        },
    )


def test_detect_finds_newer_upstream(workflow, custom, tmp_path):
    drifts = detect(tmp_path, custom, latest_resolver=lambda repo: "v0.19.0")
    assert len(drifts) == 1
    assert drifts[0].current == "0.18.1"
    assert drifts[0].fixed_versions == ["0.19.0"]


def test_detect_noop_when_same(workflow, custom, tmp_path):
    assert detect(tmp_path, custom, latest_resolver=lambda repo: "v0.18.1") == []


def test_plan_edits_workflow_file(workflow, custom, tmp_path):
    drift = detect(tmp_path, custom, latest_resolver=lambda repo: "v0.19.0")[0]
    p = plan(tmp_path, drift, custom)
    for step in p.post_steps:
        step()
    assert "0.19.0" in workflow.read_text()
