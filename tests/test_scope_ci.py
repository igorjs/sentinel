import io
from datetime import date
from pathlib import Path

from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

import scripts.scope_ci as sc
from scripts.config import Config, ScopeOverride
from scripts.runtime_eol import RuntimeEolError
from scripts.scope_ci import bump_matrix_list, find_workflows, scan

_PY = [
    {"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.7", "lts": False},
    {"cycle": "3.10", "eol": "2026-10-31", "latest": "3.10.15", "lts": False},
    {"cycle": "3.9", "eol": "2027-10-31", "latest": "3.9.20", "lts": False},
    {"cycle": "3.8", "eol": "2024-10-07", "latest": "3.8.20", "lts": False},
]
_NODE = [
    {"cycle": "22", "eol": "2027-04-30", "latest": "22.1.0", "lts": "2024-10-29"},
    {"cycle": "20", "eol": "2026-04-30", "latest": "20.11.1", "lts": "2023-10-24"},
    {"cycle": "18", "eol": "2025-04-30", "latest": "18.20.1", "lts": "2022-10-25"},
]
_UBUNTU = [
    {"cycle": "24.04", "eol": "2029-05-31", "lts": True, "latest": "24.04.1"},
    {"cycle": "22.04", "eol": "2027-06-01", "lts": True, "latest": "22.04.4"},
    {"cycle": "20.04", "eol": "2025-05-31", "lts": True, "latest": "20.04.6"},
]
_MACOS = [
    {"cycle": "15", "eol": False, "lts": False, "latest": "15.1"},
    {"cycle": "14", "eol": False, "lts": False, "latest": "14.7"},
    {"cycle": "13", "eol": "2025-09-15", "lts": False, "latest": "13.7"},
    {"cycle": "12", "eol": "2024-09-16", "lts": False, "latest": "12.7"},
]
_WINSRV = [
    {"cycle": "2025", "eol": "2034-10-10", "lts": True, "latest": "10.0.26100"},
    {"cycle": "2022", "eol": "2031-10-14", "lts": True, "latest": "10.0.20348"},
    {"cycle": "2019", "eol": "2029-01-09", "lts": True, "latest": "10.0.17763"},
    {"cycle": "23h2-ac", "eol": "2025-10-24", "lts": False, "latest": "10.0.25398"},
]


def _cycles_for(product):
    return {"ubuntu": _UBUNTU, "macos": _MACOS, "windows-server": _WINSRV}.get(product)


_TODAY = date(2026, 1, 1)
_PYCFG = ("python", 2, False)
_NODECFG = ("nodejs", 1, True)
_WF = """\
name: ci
on: push
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.8", "3.10"]  # versions
        node-version: [18, 20]
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


def test_bump_replaces_eol_keeps_supported():
    seq = ["3.8", "3.10"]
    assert bump_matrix_list(seq, _PYCFG, today=_TODAY, lead_days=30, cycles=_PY) is True
    assert seq == ["3.9", "3.10"]


def test_bump_dedupes_collision():
    seq = ["3.8", "3.9"]
    assert bump_matrix_list(seq, _PYCFG, today=_TODAY, lead_days=30, cycles=_PY) is True
    assert seq == ["3.9"]


def test_bump_single_eol_never_empties():
    seq = ["3.8"]
    assert bump_matrix_list(seq, _PYCFG, today=_TODAY, lead_days=30, cycles=_PY) is True
    assert seq == ["3.9"]


def test_bump_all_supported_no_change():
    seq = ["3.10", "3.12"]
    assert bump_matrix_list(seq, _PYCFG, today=_TODAY, lead_days=30, cycles=_PY) is False
    assert seq == ["3.10", "3.12"]


def test_bump_node_ints_preserved():
    seq = [18, 20]
    assert bump_matrix_list(seq, _NODECFG, today=_TODAY, lead_days=30, cycles=_NODE) is True
    assert seq == [20]
    assert isinstance(seq[0], int)


def test_bump_preserves_quote_style():
    seq = [DQ("3.8"), DQ("3.10")]
    assert bump_matrix_list(seq, _PYCFG, today=_TODAY, lead_days=30, cycles=_PY) is True
    assert [str(x) for x in seq] == ["3.9", "3.10"]
    assert isinstance(seq[0], DQ)  # quote style preserved


def test_bump_skips_non_numeric():
    seq = ["pypy3.10", "3.8"]
    assert bump_matrix_list(seq, _PYCFG, today=_TODAY, lead_days=30, cycles=_PY) is True
    assert seq == ["pypy3.10", "3.9"]


def test_find_workflows(tmp_path: Path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n")
    (wf / "release.yaml").write_text("on: push\n")
    (wf / "notes.txt").write_text("x")
    (tmp_path / "other.yml").write_text("x")  # not under workflows/
    found = {p.relative_to(tmp_path).as_posix() for p in find_workflows(tmp_path)}
    assert found == {".github/workflows/ci.yml", ".github/workflows/release.yaml"}


def test_find_workflows_empty(tmp_path: Path):
    assert find_workflows(tmp_path) == []


def _fetch(product):
    return _PY if product == "python" else _NODE


def test_scan_bumps_matrices(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(_WF)
    edits = scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    assert len(edits) == 1
    edit = edits[0]
    assert edit["file"] == ".github/workflows/ci.yml"
    assert set(edit["keys"]) == {"python-version", "node-version"}
    # dump the mutated doc and check the result
    buf = io.StringIO()
    edit["yaml"].dump(edit["doc"], buf)
    out = buf.getvalue()
    assert '"3.9"' in out and '"3.10"' in out and '"3.8"' not in out
    assert "[20]" in out or "- 20" in out
    assert "18" not in out
    assert "# versions" in out  # comment preserved


def test_scan_no_change_when_supported(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        'jobs:\n  t:\n    strategy:\n      matrix:\n        python-version: ["3.10", "3.12"]\n'
    )
    assert scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch) == []


def test_scan_skips_invalid_yaml(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_text("jobs: [unclosed\n")
    assert scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch) == []


def test_scan_fail_closed(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(_WF)

    def boom(_p):
        raise RuntimeEolError("down")

    assert scan(tmp_path, lead_days=30, today=_TODAY, fetch=boom) == []


def _cfg_on():
    return Config(scopes={"ci": ScopeOverride(update_runtime=True)})


def _write_wf(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(_WF)


def test_run_opted_out_returns_empty_without_fetch(tmp_path, monkeypatch):
    _write_wf(tmp_path)

    def boom(_p):
        raise AssertionError("must not fetch when opted out")

    monkeypatch.setattr(sc, "fetch_cycles", boom)
    assert sc.run(tmp_path, Config(), None, dry_run=True) == []


def test_run_opted_in_opens_pr_dry_run(tmp_path, monkeypatch):
    _write_wf(tmp_path)
    monkeypatch.setattr(sc, "_today", lambda: _TODAY)
    monkeypatch.setattr(sc, "fetch_cycles", _fetch)
    results = sc.run(tmp_path, _cfg_on(), None, dry_run=True)
    assert len(results) == 1 and results[0].kind == "noop"  # dry-run


def test_run_apply_failure_falls_back_to_issue(tmp_path, monkeypatch):
    import subprocess as _sp

    _write_wf(tmp_path)
    monkeypatch.setattr(sc, "_today", lambda: _TODAY)
    monkeypatch.setattr(sc, "fetch_cycles", _fetch)
    monkeypatch.setattr(
        sc, "apply_plan", lambda *a, **k: (_ for _ in ()).throw(_sp.CalledProcessError(1, ["git"]))
    )
    results = sc.run(tmp_path, _cfg_on(), None, dry_run=True)
    assert any(r.key == "ci-eol" for r in results)


def test_apply_writes_file_preserving_layout(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    p = wf / "ci.yml"
    p.write_text(_WF)
    edits = sc.scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    plan = sc._plan(edits)
    for step in plan.post_steps:
        step()
    out = p.read_text()
    # matrix bumped, quoting + inline comment preserved
    assert '        python-version: ["3.9", "3.10"]  # versions\n' in out
    assert '"3.8"' not in out
    # untouched lines keep their exact indentation (no whole-file re-indent)
    assert "    runs-on: ubuntu-latest\n" in out
    assert "    steps:\n      - run: echo hi\n" in out


def test_run_dump_error_falls_back_to_issue(tmp_path, monkeypatch):
    from ruamel.yaml.error import YAMLError

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(_WF)
    monkeypatch.setattr(sc, "_today", lambda: _TODAY)
    monkeypatch.setattr(sc, "fetch_cycles", _fetch)
    monkeypatch.setattr(sc, "apply_plan", lambda *a, **k: (_ for _ in ()).throw(YAMLError("boom")))
    results = sc.run(
        tmp_path, Config(scopes={"ci": ScopeOverride(update_runtime=True)}), None, dry_run=True
    )
    assert any(r.key == "ci-eol" for r in results)


def test_no_bump_preserves_existing_dups():
    seq = ["3.10", "3.10"]
    assert (
        sc.bump_matrix_list(seq, ("python", 2, False), today=_TODAY, lead_days=30, cycles=_PY)
        is False
    )
    assert seq == ["3.10", "3.10"]


def test_split_version_suffix():
    assert sc._split_version_suffix("22.04-arm") == ("22.04", "-arm")
    assert sc._split_version_suffix("13-large") == ("13", "-large")
    assert sc._split_version_suffix("2019") == ("2019", "")
    assert sc._split_version_suffix("latest") is None
    assert sc._split_version_suffix("latest-xlarge") is None


def test_parse_runner_label_bare():
    assert sc.parse_runner_label("ubuntu-22.04") == ("ubuntu", "22.04", "22.04", "")
    assert sc.parse_runner_label("macos-13") == ("macos", "13", "13", "")
    assert sc.parse_runner_label("windows-2019") == ("windows", "2019", "2019", "")


def test_parse_runner_label_suffix():
    assert sc.parse_runner_label("macos-13-large") == ("macos", "13", "13", "-large")
    assert sc.parse_runner_label("ubuntu-22.04-arm") == ("ubuntu", "22.04", "22.04", "-arm")


def test_parse_runner_label_skips():
    assert sc.parse_runner_label("ubuntu-latest") is None
    assert sc.parse_runner_label("macos-latest-xlarge") is None
    assert sc.parse_runner_label("${{ matrix.os }}") is None
    assert sc.parse_runner_label("self-hosted") is None
    assert sc.parse_runner_label("freebsd-13") is None
    assert sc.parse_runner_label("ubuntu") is None
    assert sc.parse_runner_label(18) is None


def test_bump_runner_label_ubuntu_eol():
    out = sc.bump_runner_label("ubuntu-20.04", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
    assert out == "ubuntu-22.04"


def test_bump_runner_label_ubuntu_supported():
    assert (
        sc.bump_runner_label("ubuntu-22.04", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
        is None
    )


def test_bump_runner_label_macos_skips_eol_target():
    # 13 is also EOL, so 12 bumps to the oldest *supported* cycle, 14
    assert (
        sc.bump_runner_label("macos-12", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
        == "macos-14"
    )
    assert (
        sc.bump_runner_label("macos-13", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
        == "macos-14"
    )


def test_bump_runner_label_preserves_suffix():
    out = sc.bump_runner_label("macos-13-large", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
    assert out == "macos-14-large"


def test_bump_runner_label_windows_vendor_supported():
    # vendor EOL 2029, so no bump today (the documented runner-lag case)
    assert (
        sc.bump_runner_label("windows-2019", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
        is None
    )


def test_bump_runner_label_non_label():
    assert (
        sc.bump_runner_label("ubuntu-latest", today=_TODAY, lead_days=30, cycles_for=_cycles_for)
        is None
    )


def test_bump_runner_label_fail_closed():
    assert (
        sc.bump_runner_label("ubuntu-20.04", today=_TODAY, lead_days=30, cycles_for=lambda _p: None)
        is None
    )


def test_bump_os_list_mixed_per_os_dedupe_and_suffix():
    seq = ["ubuntu-20.04", "macos-13-large", "windows-2019", "self-hosted", "ubuntu-22.04"]
    assert sc.bump_os_list(seq, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is True
    # ubuntu-20.04 -> 22.04 collides with the existing ubuntu-22.04 -> deduped
    assert seq == ["ubuntu-22.04", "macos-14-large", "windows-2019", "self-hosted"]


def test_bump_os_list_no_change_returns_false():
    seq = ["ubuntu-22.04", "macos-14", "windows-2022"]
    assert sc.bump_os_list(seq, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is False
    assert seq == ["ubuntu-22.04", "macos-14", "windows-2022"]


def test_bump_os_list_never_empties():
    seq = ["ubuntu-20.04"]
    assert sc.bump_os_list(seq, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is True
    assert seq == ["ubuntu-22.04"]


def test_bump_os_list_preserves_quote_style():
    seq = [DQ("ubuntu-20.04")]
    assert sc.bump_os_list(seq, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is True
    assert [str(x) for x in seq] == ["ubuntu-22.04"]
    assert isinstance(seq[0], DQ)


def test_bump_runs_on_scalar_eol():
    job = {"runs-on": "ubuntu-20.04"}
    assert sc._bump_runs_on(job, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is True
    assert job["runs-on"] == "ubuntu-22.04"


def test_bump_runs_on_scalar_supported():
    job = {"runs-on": "ubuntu-22.04"}
    assert sc._bump_runs_on(job, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is False
    assert job["runs-on"] == "ubuntu-22.04"


def test_bump_runs_on_scalar_latest_untouched():
    job = {"runs-on": "ubuntu-latest"}
    assert sc._bump_runs_on(job, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is False
    assert job["runs-on"] == "ubuntu-latest"


def test_bump_runs_on_list_no_dedupe():
    job = {"runs-on": ["ubuntu-20.04", "self-hosted"]}
    assert sc._bump_runs_on(job, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is True
    assert job["runs-on"] == ["ubuntu-22.04", "self-hosted"]


def test_bump_runs_on_dict_form_skipped():
    job = {"runs-on": {"group": "g", "labels": ["ubuntu-20.04"]}}
    assert sc._bump_runs_on(job, today=_TODAY, lead_days=30, cycles_for=_cycles_for) is False


_WF_OS = """\
name: ci
on: push
jobs:
  build:
    runs-on: ubuntu-20.04
    steps:
      - run: echo build
  test:
    strategy:
      matrix:
        os: ["ubuntu-20.04", "macos-13-large", "windows-2019"]
        python-version: ["3.8", "3.10"]
    runs-on: ${{ matrix.os }}
    steps:
      - run: echo test
"""


def _fetch_all(product):
    return {
        "python": _PY,
        "nodejs": _NODE,
        "ubuntu": _UBUNTU,
        "macos": _MACOS,
        "windows-server": _WINSRV,
    }[product]


def test_scan_bumps_runner_os_and_matrix(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(_WF_OS)
    edits = sc.scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch_all)
    assert len(edits) == 1
    assert set(edits[0]["keys"]) == {"runs-on", "matrix.os", "python-version"}
    buf = io.StringIO()
    edits[0]["yaml"].dump(edits[0]["doc"], buf)
    out = buf.getvalue()
    assert "runs-on: ubuntu-22.04" in out  # scalar bumped
    assert "${{ matrix.os }}" in out  # expression untouched
    assert '"macos-14-large"' in out  # suffix + quoting preserved
    assert "windows-2019" in out  # vendor-supported, untouched
    assert '"ubuntu-22.04"' in out and '"ubuntu-20.04"' not in out
    assert '"3.9"' in out and '"3.8"' not in out


def test_scan_runs_on_only_workflow(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "deploy.yml").write_text(
        "jobs:\n  d:\n    runs-on: ubuntu-20.04\n    steps:\n      - run: echo x\n"
    )
    edits = sc.scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch_all)
    assert len(edits) == 1 and edits[0]["keys"] == ["runs-on"]
