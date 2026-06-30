import subprocess

import pytest

from scripts import pr as pr_mod
from scripts.models import Plan
from scripts.pr import assert_pushable, branch_name


def test_branch_name_basic():
    assert branch_name("rust", "RUSTSEC-2024-1") == "sentinel/rust/rustsec-2024-1"


def test_branch_name_lowercases():
    assert branch_name("Rust", "Foo") == "sentinel/rust/foo"


def test_branch_name_replaces_unsafe_chars():
    assert branch_name("go", "GO 2024 / 12") == "sentinel/go/go-2024-12"


def test_branch_name_collapses_repeats():
    assert branch_name("go", "a//b") == "sentinel/go/a-b"


def test_assert_pushable_allows_sentinel_branch():
    # Returns None and does not raise.
    assert assert_pushable("sentinel/rust/rustsec-2024-1") is None


@pytest.mark.parametrize("branch", ["main", "master", "develop", "sentinel-evil", "../sentinel/x"])
def test_assert_pushable_rejects_non_sentinel_branch(branch):
    with pytest.raises(ValueError, match="non-sentinel branch"):
        assert_pushable(branch)


def _record_subprocess(monkeypatch):
    calls: list[list[str]] = []

    def rec(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pr_mod.subprocess, "run", rec)
    return calls


def test_push_branch_fetches_then_force_with_lease(tmp_path, monkeypatch):
    calls = _record_subprocess(monkeypatch)
    pr_mod._push_branch("sentinel/rust/x", tmp_path)

    assert calls[0][:2] == ["git", "fetch"]  # establish remote-tracking ref first
    push = calls[1]
    assert push[:2] == ["git", "push"]
    assert "--force-with-lease" in push
    assert "sentinel/rust/x:sentinel/rust/x" in push  # explicit refspec, not implicit


def test_push_branch_refuses_non_sentinel_branch(tmp_path, monkeypatch):
    calls = _record_subprocess(monkeypatch)
    with pytest.raises(ValueError):
        pr_mod._push_branch("main", tmp_path)
    assert calls == []  # never invoked git


def _fake_gh(monkeypatch, list_stdout: str):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        stdout = list_stdout if "list" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(pr_mod.subprocess, "run", fake_run)
    return calls


def test_issue_dedup_enumerates_by_label_not_fuzzy_search(tmp_path, monkeypatch):
    calls = _fake_gh(monkeypatch, '[{"number": 7, "title": "T"}]')
    result = pr_mod.open_issue_fallback(
        scope="rust", key="k", title="T", body="b", dry_run=False, workdir=tmp_path
    )
    list_cmd = calls[0]
    assert "--label" in list_cmd and "sentinel" in list_cmd  # direct, consistent listing
    assert "--search" not in list_cmd  # not the eventually-consistent fuzzy index
    assert not any("create" in c for c in calls)  # exact title already open -> no dupe
    assert result.kind == "noop"


def test_issue_created_when_no_open_match(tmp_path, monkeypatch):
    calls = _fake_gh(monkeypatch, "[]")
    result = pr_mod.open_issue_fallback(
        scope="rust", key="k", title="T", body="b", dry_run=False, workdir=tmp_path
    )
    assert any("create" in c for c in calls)
    assert result.kind == "issue"


def test_issue_dedup_requires_exact_title_match(tmp_path, monkeypatch):
    # A different open sentinel issue must not suppress creation.
    calls = _fake_gh(monkeypatch, '[{"number": 7, "title": "different title"}]')
    result = pr_mod.open_issue_fallback(
        scope="rust", key="k", title="T", body="b", dry_run=False, workdir=tmp_path
    )
    assert any("create" in c for c in calls)
    assert result.kind == "issue"


def _fake_apply_subprocess(monkeypatch):
    """Drive apply_plan past the no-op check to the gh pr create path."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["git", "diff", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")  # changes present
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, " M file.txt\n", "")
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pr_mod.subprocess, "run", fake_run)
    return calls


def _plan() -> Plan:
    return Plan(
        scope="rust",
        key="K",
        branch="sentinel/rust/k",
        title="t",
        body="b",
        files_changed=[],
        commands=[],
        post_steps=(),
    )


def test_apply_plan_uses_custom_pr_labels(tmp_path, monkeypatch):
    calls = _fake_apply_subprocess(monkeypatch)
    pr_mod.apply_plan(
        _plan(),
        dry_run=False,
        workdir=tmp_path,
        base_sha="abc",
        pr_labels=["security", "automated"],
    )
    create = next(c for c in calls if c[:3] == ["gh", "pr", "create"])
    assert "--label" in create
    assert "security" in create
    assert "dependencies" not in create  # custom labels replace defaults


def test_apply_plan_defaults_pr_labels(tmp_path, monkeypatch):
    calls = _fake_apply_subprocess(monkeypatch)
    pr_mod.apply_plan(_plan(), dry_run=False, workdir=tmp_path, base_sha="abc")
    create = next(c for c in calls if c[:3] == ["gh", "pr", "create"])
    assert "dependencies" in create and "automated" in create
