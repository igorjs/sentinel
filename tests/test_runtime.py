from datetime import date
from datetime import date as _date
from pathlib import Path

from scripts.models import Drift as _Drift
from scripts.runtime import (
    MISE_FILES,
    PRODUCTS,
    detect_runtime_drift,
    read_engines_node,
    read_mise_tool,
    read_pin,
    read_requires_python,
    read_tool_versions,
    runtime_plan,
    write_engines_node,
    write_mise_tool,
    write_pin,
    write_requires_python,
    write_tool_versions,
)


def test_requires_python_roundtrip(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1"\nrequires-python = ">=3.8,<4.0"\n'
    )
    assert read_requires_python(tmp_path) == ">=3.8,<4.0"
    write_requires_python(tmp_path, ">=3.9,<4.0")
    assert read_requires_python(tmp_path) == ">=3.9,<4.0"
    # tomlkit preserves surrounding content
    assert 'name = "x"' in (tmp_path / "pyproject.toml").read_text()


def test_engines_node_minimal_diff(tmp_path: Path):
    original = '{\n  "name": "x",\n  "engines": {\n    "node": ">=18"\n  }\n}\n'
    (tmp_path / "package.json").write_text(original)
    assert read_engines_node(tmp_path) == ">=18"
    write_engines_node(tmp_path, ">=20")
    after = (tmp_path / "package.json").read_text()
    assert '"node": ">=20"' in after
    assert after == original.replace(">=18", ">=20")  # only the value changed


def test_engines_node_absent(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    assert read_engines_node(tmp_path) is None


def test_pin_roundtrip(tmp_path: Path):
    (tmp_path / ".nvmrc").write_text("18\n")
    assert read_pin(".nvmrc")(tmp_path) == "18"
    write_pin(".nvmrc")(tmp_path, "20")
    assert (tmp_path / ".nvmrc").read_text() == "20\n"  # trailing newline preserved


PY_CYCLES = [
    {"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.7", "lts": False},
    {"cycle": "3.9", "eol": "2027-10-31", "latest": "3.9.20", "lts": False},
    {"cycle": "3.8", "eol": "2024-10-07", "latest": "3.8.20", "lts": False},
]
# TODAY chosen so 3.8 is EOL but 3.9 is still supported -> 3.9 is the oldest
# still-supported target.
TODAY = date(2026, 1, 1)


def _fake_fetch(_product):
    return PY_CYCLES


def test_detect_runtime_drift_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )
    (tmp_path / ".python-version").write_text("3.8.10\n")
    drift = detect_runtime_drift(tmp_path, "python", lead_days=30, today=TODAY, fetch=_fake_fetch)
    assert drift is not None
    edits = {e["label"]: e["new"] for e in drift.raw["edits"]}
    assert edits["requires-python"] == ">=3.9"
    assert edits[".python-version"] == "3.9.20"  # patch granularity -> latest


def test_detect_runtime_drift_none_when_supported(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.12"\n'
    )
    assert (
        detect_runtime_drift(tmp_path, "python", lead_days=30, today=TODAY, fetch=_fake_fetch)
        is None
    )


def test_detect_runtime_drift_unparseable_recorded(tmp_path):
    (tmp_path / ".nvmrc").write_text("lts/iron\n")

    def node_fetch(_p):
        return [{"cycle": "20", "eol": "2026-04-30", "latest": "20.11.1", "lts": "2023-10-24"}]

    drift = detect_runtime_drift(
        tmp_path, "javascript", lead_days=30, today=TODAY, fetch=node_fetch
    )
    assert drift is not None
    assert drift.raw["edits"] == []
    assert ".nvmrc" in drift.raw["unparseable"]


def test_detect_runtime_drift_fail_closed(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )

    def boom(_p):
        from scripts.runtime_eol import RuntimeEolError

        raise RuntimeEolError("down")

    assert detect_runtime_drift(tmp_path, "python", lead_days=30, today=TODAY, fetch=boom) is None


def test_runtime_plan_applies_edits(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )
    drift = detect_runtime_drift(tmp_path, "python", lead_days=30, today=TODAY, fetch=_fake_fetch)
    p = runtime_plan(tmp_path, drift, "python")
    assert p.key == "runtime-eol"
    assert "pyproject.toml" in p.files_changed
    for step in p.post_steps:
        step()
    assert read_requires_python(tmp_path) == ">=3.9"


def test_runtime_results_opted_out_returns_empty_without_fetch(tmp_path, monkeypatch):
    import scripts.runtime as rtmod
    from scripts.config import Config

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )

    # default config -> update_runtime False; must short-circuit BEFORE any fetch
    def boom(_p):
        raise AssertionError("fetch must not run when opted out")

    monkeypatch.setattr(rtmod, "fetch_cycles", boom)
    assert rtmod.runtime_results(tmp_path, Config(), "python", dry_run=True) == []


def test_runtime_results_opted_in_returns_pr(tmp_path, monkeypatch):
    import scripts.runtime as rtmod
    from scripts.config import Config, ScopeOverride

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )
    monkeypatch.setattr(rtmod, "_today", lambda: TODAY)
    monkeypatch.setattr(rtmod, "fetch_cycles", _fake_fetch)
    cfg = Config(scopes={"python": ScopeOverride(update_runtime=True)})
    results = rtmod.runtime_results(tmp_path, cfg, "python", dry_run=True)
    runtime = [r for r in results if r.key == "runtime-eol"]
    assert len(runtime) == 1 and runtime[0].kind == "noop"


def test_detect_runtime_drift_malformed_cycles_fail_closed(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )

    def malformed_fetch(_product):
        return [{"cycle": "tip"}, {"weird": True}]

    drift = detect_runtime_drift(
        tmp_path, "python", lead_days=30, today=date(2026, 1, 1), fetch=malformed_fetch
    )
    assert drift is None  # fail-closed: malformed data -> no drift, no exception


def test_read_tool_versions_primary(tmp_path):
    (tmp_path / ".tool-versions").write_text(
        "# managed by asdf\npython 3.8.10 3.9.5\nnodejs 18.16.0  # lts\n"
    )
    assert read_tool_versions("python")(tmp_path) == "3.8.10"
    assert read_tool_versions("nodejs", "node")(tmp_path) == "18.16.0"


def test_read_tool_versions_node_alias(tmp_path):
    (tmp_path / ".tool-versions").write_text("node 18.16.0\n")
    assert read_tool_versions("nodejs", "node")(tmp_path) == "18.16.0"


def test_read_tool_versions_absent(tmp_path):
    assert read_tool_versions("python")(tmp_path) is None  # no file
    (tmp_path / ".tool-versions").write_text("# only a comment\nruby 3.2.0\n")
    assert read_tool_versions("python")(tmp_path) is None  # tool not present


def test_write_tool_versions_minimal_diff(tmp_path):
    original = "# header\npython 3.8.10 3.9.5  # keep\nnodejs 18.16.0\n"
    (tmp_path / ".tool-versions").write_text(original)
    write_tool_versions("python")(tmp_path, "3.9.20")
    after = (tmp_path / ".tool-versions").read_text()
    # only the python primary token changed; fallback, inline comment, nodejs line, header intact
    assert after == "# header\npython 3.9.20 3.9.5  # keep\nnodejs 18.16.0\n"


def test_write_tool_versions_no_trailing_newline_preserved(tmp_path):
    (tmp_path / ".tool-versions").write_text("python 3.8.10")  # no trailing newline
    write_tool_versions("python")(tmp_path, "3.9.20")
    assert (tmp_path / ".tool-versions").read_text() == "python 3.9.20"


def test_write_tool_versions_absent_raises(tmp_path):
    import pytest

    from scripts.runtime import write_tool_versions

    (tmp_path / ".tool-versions").write_text("ruby 3.2.0\n")
    with pytest.raises(KeyError):
        write_tool_versions("python")(tmp_path, "3.9.20")


def test_read_tool_versions_skips_line_without_version(tmp_path):
    from scripts.runtime import read_tool_versions

    (tmp_path / ".tool-versions").write_text("python\nnodejs 18.16.0\n")
    # `python` line has no version -> skipped; nodejs still readable
    assert read_tool_versions("python")(tmp_path) is None
    assert read_tool_versions("nodejs", "node")(tmp_path) == "18.16.0"


def test_mise_files_constant():
    assert MISE_FILES == ("mise.toml", ".mise.toml", ".config/mise/config.toml")


def test_read_mise_tool_value_forms(tmp_path):
    (tmp_path / "mise.toml").write_text('[tools]\npython = "3.8.10"\nnode = ["18.16.0", "20"]\n')
    assert read_mise_tool("mise.toml", "python")(tmp_path) == "3.8.10"
    assert read_mise_tool("mise.toml", "node")(tmp_path) == "18.16.0"  # array -> first


def test_read_mise_tool_table_form_and_absent(tmp_path):
    (tmp_path / ".mise.toml").write_text(
        '[tools]\npython = { version = "3.8.10", virtualenv = ".venv" }\n'
    )
    assert read_mise_tool(".mise.toml", "python")(tmp_path) == "3.8.10"  # table -> version
    assert read_mise_tool(".mise.toml", "node")(tmp_path) is None  # key absent
    assert read_mise_tool("mise.toml", "python")(tmp_path) is None  # file absent


def test_write_mise_tool_string_form_minimal_diff(tmp_path):
    (tmp_path / "mise.toml").write_text(
        '# project tools\n[tools]\npython = "3.8.10"  # pinned\nnode = "18.16.0"\n'
    )
    write_mise_tool("mise.toml", "python")(tmp_path, "3.9.20")
    after = (tmp_path / "mise.toml").read_text()
    assert 'python = "3.9.20"' in after
    assert "# pinned" in after and 'node = "18.16.0"' in after and "# project tools" in after


def test_write_mise_tool_array_form(tmp_path):
    (tmp_path / "mise.toml").write_text('[tools]\nnode = ["18.16.0", "20"]\n')
    write_mise_tool("mise.toml", "node")(tmp_path, "20.11.1")
    after = (tmp_path / "mise.toml").read_text()
    assert '"20.11.1"' in after and '"20"' in after  # primary bumped, fallback kept


def test_write_mise_tool_table_form(tmp_path):
    (tmp_path / "mise.toml").write_text(
        '[tools]\npython = { version = "3.8.10", virtualenv = ".venv" }\n'
    )
    write_mise_tool("mise.toml", "python")(tmp_path, "3.9.20")
    after = (tmp_path / "mise.toml").read_text()
    assert '"3.9.20"' in after and "virtualenv" in after  # version bumped, option kept


def test_registry_includes_new_decls():
    py_files = {d.file for d in PRODUCTS["python"].decls}
    js_files = {d.file for d in PRODUCTS["javascript"].decls}
    assert {".tool-versions", "mise.toml", ".mise.toml", ".config/mise/config.toml"} <= py_files
    assert {".tool-versions", "mise.toml", ".mise.toml", ".config/mise/config.toml"} <= js_files
    assert len(PRODUCTS["python"].decls) == 6
    assert len(PRODUCTS["javascript"].decls) == 7


_PY = [
    {"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.7", "lts": False},
    {"cycle": "3.9", "eol": "2027-10-31", "latest": "3.9.20", "lts": False},
    {"cycle": "3.8", "eol": "2024-10-07", "latest": "3.8.20", "lts": False},
]
_NODE = [
    {"cycle": "22", "eol": "2027-04-30", "latest": "22.1.0", "lts": "2024-10-29"},
    {"cycle": "20", "eol": "2026-04-30", "latest": "20.11.1", "lts": "2023-10-24"},
    {"cycle": "18", "eol": "2025-04-30", "latest": "18.20.1", "lts": "2022-10-25"},
]
_TODAY = _date(2026, 1, 1)


def test_detect_bumps_tool_versions_python(tmp_path):
    (tmp_path / ".tool-versions").write_text("python 3.8.10\n")
    drift = detect_runtime_drift(
        tmp_path, "python", lead_days=30, today=_TODAY, fetch=lambda _p: _PY
    )
    edit = next(e for e in drift.raw["edits"] if e["file"] == ".tool-versions")
    assert edit["current"] == "3.8.10" and edit["new"] == "3.9.20"


def test_detect_bumps_mise_node(tmp_path):
    (tmp_path / "mise.toml").write_text('[tools]\nnode = "18.16.0"\n')
    drift = detect_runtime_drift(
        tmp_path, "javascript", lead_days=30, today=_TODAY, fetch=lambda _p: _NODE
    )
    edit = next(e for e in drift.raw["edits"] if e["file"] == "mise.toml")
    assert edit["current"] == "18.16.0" and edit["new"] == "20.11.1"


def test_detect_tool_versions_unparseable_latest(tmp_path):
    (tmp_path / ".tool-versions").write_text("python latest\n")
    drift = detect_runtime_drift(
        tmp_path, "python", lead_days=30, today=_TODAY, fetch=lambda _p: _PY
    )
    assert ".tool-versions" in drift.raw["unparseable"]


def test_detect_skips_malformed_mise_fail_closed(tmp_path):
    from datetime import date

    (tmp_path / "mise.toml").write_text("[tools]\npython = \n")  # invalid TOML
    (tmp_path / ".tool-versions").write_text("python 3.8.10\n")
    drift = detect_runtime_drift(
        tmp_path, "python", lead_days=30, today=date(2026, 1, 1), fetch=lambda _p: _PY
    )
    # malformed mise.toml is skipped (no crash); the valid .tool-versions is still bumped
    assert drift is not None
    files = [e["file"] for e in drift.raw["edits"]]
    assert ".tool-versions" in files and "mise.toml" not in files


def _floor_drift(file, current, new, scope="python"):
    edits = [
        {"label": file, "file": file, "current": current, "new": new, "write": lambda *a: None}
    ]
    return _Drift(
        scope=scope,
        key="runtime-eol",
        summary="x",
        fixed_versions=[new],
        current="x",
        severity="none",
        raw={"product": "python", "edits": edits, "unparseable": []},
    )


def test_runtime_plan_refreshes_uv_lock_on_floor_bump(tmp_path):
    (tmp_path / "uv.lock").write_text('version = 1\nrequires-python = ">=3.8"\n')
    plan = runtime_plan(tmp_path, _floor_drift("pyproject.toml", ">=3.8", ">=3.9"), "python")
    cmds = [getattr(s, "cmd", None) for s in plan.post_steps]
    assert ["uv", "lock"] in cmds
    assert "uv.lock" in plan.files_changed


def test_runtime_plan_no_refresh_without_lockfile(tmp_path):
    plan = runtime_plan(tmp_path, _floor_drift("pyproject.toml", ">=3.8", ">=3.9"), "python")
    assert all(getattr(s, "cmd", None) is None for s in plan.post_steps)  # only _apply
    assert plan.files_changed == ["pyproject.toml"]


def test_runtime_plan_no_refresh_for_pin_only_edit(tmp_path):
    (tmp_path / "uv.lock").write_text("version = 1\n")
    plan = runtime_plan(tmp_path, _floor_drift(".python-version", "3.8", "3.9"), "python")
    assert all(getattr(s, "cmd", None) is None for s in plan.post_steps)
    assert "uv.lock" not in plan.files_changed


def test_runtime_plan_npm_refresh_only_skips_pnpm(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n")
    plan = runtime_plan(
        tmp_path, _floor_drift("package.json", ">=18", ">=20", scope="javascript"), "javascript"
    )
    cmds = [getattr(s, "cmd", None) for s in plan.post_steps]
    assert ["npm", "install", "--package-lock-only", "--ignore-scripts"] in cmds
    assert "package-lock.json" in plan.files_changed
    assert "pnpm-lock.yaml" not in plan.files_changed


def test_runtime_plan_edit_runs_before_refresh(tmp_path, monkeypatch):
    import scripts.runtime as rt

    (tmp_path / "uv.lock").write_text("version = 1\n")
    calls = []
    edits = [
        {
            "label": "requires-python",
            "file": "pyproject.toml",
            "current": ">=3.8",
            "new": ">=3.9",
            "write": lambda *a: calls.append("edit"),
        }
    ]
    drift = _Drift(
        scope="python",
        key="runtime-eol",
        summary="x",
        fixed_versions=[">=3.9"],
        current="x",
        severity="none",
        raw={"product": "python", "edits": edits, "unparseable": []},
    )
    monkeypatch.setattr(rt.subprocess, "run", lambda *a, **k: calls.append("refresh"))
    plan = runtime_plan(tmp_path, drift, "python")
    for step in plan.post_steps:
        step()
    assert calls == ["edit", "refresh"]


def test_runtime_results_lock_refresh_failure_falls_back_to_issue(tmp_path, monkeypatch):
    import scripts.runtime as rt
    from scripts.config import Config, ScopeOverride

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )
    (tmp_path / "uv.lock").write_text("version = 1\n")
    monkeypatch.setattr(rt, "_today", lambda: _date(2026, 1, 1))
    monkeypatch.setattr(rt, "fetch_cycles", lambda _p: _PY)

    def boom(*a, **k):
        raise rt.LockRefreshError("boom")

    monkeypatch.setattr(rt, "apply_plan", boom)
    cfg = Config(scopes={"python": ScopeOverride(update_runtime=True)})
    # dry_run=True so base_sha is "" (no git in tmp_path); the monkeypatched
    # apply_plan still raises, exercising the except branch.
    results = rt.runtime_results(tmp_path, cfg, "python", dry_run=True)
    assert any(r.key == "runtime-eol-lock-refresh" for r in results)


def test_refresh_step_absent_pm_raises_lock_refresh_error(tmp_path):
    from scripts.runtime import LockRefreshError, _refresh_step

    step = _refresh_step(tmp_path, ["sentinel-no-such-pm-xyz", "lock"])
    import pytest

    with pytest.raises(LockRefreshError):
        step()


def test_refresh_step_nonzero_exit_raises_lock_refresh_error(tmp_path):
    import sys

    import pytest

    from scripts.runtime import LockRefreshError, _refresh_step

    step = _refresh_step(tmp_path, [sys.executable, "-c", "import sys; sys.exit(1)"])
    with pytest.raises(LockRefreshError):
        step()


def test_runtime_results_propagates_non_refresh_error(tmp_path, monkeypatch):
    # A CalledProcessError from apply_plan (git/gh), NOT a refresh failure,
    # must propagate (not be masked as a lockfile-refresh issue).
    import subprocess as _sp

    import pytest

    import scripts.runtime as rt
    from scripts.config import Config, ScopeOverride

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\nrequires-python = ">=3.8"\n'
    )
    monkeypatch.setattr(rt, "_today", lambda: _date(2026, 1, 1))
    monkeypatch.setattr(rt, "fetch_cycles", lambda _p: _PY)
    monkeypatch.setattr(
        rt,
        "apply_plan",
        lambda *a, **k: (_ for _ in ()).throw(_sp.CalledProcessError(1, ["git", "push"])),
    )
    cfg = Config(scopes={"python": ScopeOverride(update_runtime=True)})
    with pytest.raises(_sp.CalledProcessError):
        rt.runtime_results(tmp_path, cfg, "python", dry_run=True)
