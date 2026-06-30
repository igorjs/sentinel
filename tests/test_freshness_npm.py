import json
import subprocess
from types import SimpleNamespace

import pytest

import scripts.freshness_npm as N
from scripts.freshness import FreshnessError, Outdated, Selection

_OUTDATED_JSON = json.dumps(
    {
        "lodash": {"current": "4.17.20", "wanted": "4.17.21", "latest": "5.0.0"},
        "express": {"wanted": "4.18.2", "latest": "4.18.2"},  # no current -> from lock
    }
)
_LOCK = json.dumps(
    {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"lodash": "^4.17.0", "express": "^4.18.0"}},
            "node_modules/lodash": {"version": "4.17.20"},
            "node_modules/express": {"version": "4.18.0"},
        },
    }
)


def _wd(tmp_path, *, lock=True, outdated_rc=1, stdout=_OUTDATED_JSON, oserror=False):
    if lock:
        (tmp_path / "package-lock.json").write_text(_LOCK)

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        if oserror:
            raise OSError("npm not found")
        return SimpleNamespace(returncode=outdated_rc, stdout=stdout, stderr="")

    return fake_run


def test_list_outdated_parses(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path))
    out = N.list_outdated(tmp_path)
    assert Outdated("lodash", "4.17.20", "4.17.21", "5.0.0") in out
    # express current filled from the lockfile
    assert Outdated("express", "4.18.0", "4.18.2", "4.18.2") in out


def test_list_outdated_no_lockfile_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path, lock=False))
    assert N.list_outdated(tmp_path) == []


def test_list_outdated_exit0_none(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path, outdated_rc=0, stdout=""))
    assert N.list_outdated(tmp_path) == []


def test_list_outdated_bad_json_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path, stdout="not json"))
    with pytest.raises(FreshnessError):
        N.list_outdated(tmp_path)


def test_list_outdated_npm_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path, oserror=True))
    with pytest.raises(FreshnessError):
        N.list_outdated(tmp_path)


def test_list_outdated_unexpected_exit_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path, outdated_rc=2, stdout=""))
    with pytest.raises(FreshnessError):
        N.list_outdated(tmp_path)


def test_list_outdated_non_dict_root_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _wd(tmp_path, stdout="[]"))
    with pytest.raises(FreshnessError):
        N.list_outdated(tmp_path)


def test_list_outdated_bad_lockfile_root_raises(tmp_path, monkeypatch):
    (tmp_path / "package-lock.json").write_text("[]")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout='{"lodash": {"current": "1.0.0", "wanted": "1.1.0", "latest": "2.0.0"}}',
            stderr="",
        ),
    )
    with pytest.raises(FreshnessError):
        N.list_outdated(tmp_path)


def test_list_outdated_workspace_list_shape(tmp_path, monkeypatch):
    stdout = '{"pkg": [{"current": "1.0.0", "wanted": "2.0.0", "latest": "2.0.0"}]}'
    (tmp_path / "package-lock.json").write_text(_LOCK)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=stdout, stderr=""),
    )
    out = N.list_outdated(tmp_path)
    assert any(o.name == "pkg" and o.current == "1.0.0" for o in out)


def test_apply_in_range_runs_npm_update(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    N.apply(tmp_path, [Selection("lodash", "4.17.20", "4.17.21", False)])
    assert calls == [["npm", "update", "lodash", "--package-lock-only", "--ignore-scripts"]]


def test_apply_major_edits_manifest_then_installs(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"lodash": "^4.17.0"}}, indent=2)
    )
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    N.apply(tmp_path, [Selection("lodash", "4.17.20", "5.0.0", True)])
    manifest = (tmp_path / "package.json").read_text()
    assert '"lodash": "^5.0.0"' in manifest
    assert ["npm", "install", "--package-lock-only", "--ignore-scripts"] in calls


def test_apply_major_unlocatable_constraint_skipped(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {}}, indent=2))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    # no crash, manifest unchanged for the missing dep
    N.apply(tmp_path, [Selection("ghost", "1.0.0", "2.0.0", True)])
    assert (tmp_path / "package.json").read_text() == json.dumps({"dependencies": {}}, indent=2)


def test_apply_npm_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    with pytest.raises(FreshnessError):
        N.apply(tmp_path, [Selection("lodash", "4.17.20", "4.17.21", False)])
