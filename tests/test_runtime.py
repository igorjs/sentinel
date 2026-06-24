from datetime import date
from pathlib import Path

from scripts.runtime import (
    detect_runtime_drift,
    read_engines_node,
    read_pin,
    read_requires_python,
    runtime_plan,
    write_engines_node,
    write_pin,
    write_requires_python,
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
