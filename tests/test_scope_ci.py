from datetime import date
from pathlib import Path

from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

from scripts.scope_ci import bump_matrix_list, find_workflows

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
_TODAY = date(2026, 1, 1)
_PYCFG = ("python", 2, False)
_NODECFG = ("nodejs", 1, True)


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
