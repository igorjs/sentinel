import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = _PROJECT_ROOT
    return subprocess.run(
        [sys.executable, "-m", "scripts.sentinel", *args],
        capture_output=True, check=True, text=True, cwd=cwd, env=env,
    )


def test_discover_emits_rust_when_cargo_lock_present(tmp_path: Path):
    (tmp_path / "Cargo.lock").write_text("# stub\n")
    result = run_cli("--mode", "discover", cwd=tmp_path)
    scopes = json.loads(result.stdout.strip())
    assert "rust" in scopes


def test_discover_emits_go_when_go_mod_present(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module x\ngo 1.24.4\n")
    result = run_cli("--mode", "discover", cwd=tmp_path)
    scopes = json.loads(result.stdout.strip())
    assert "go" in scopes


def test_discover_emits_javascript_when_package_json_present(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}")
    result = run_cli("--mode", "discover", cwd=tmp_path)
    scopes = json.loads(result.stdout.strip())
    assert "javascript" in scopes


def test_discover_emits_python_when_pyproject_present(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1'\n")
    result = run_cli("--mode", "discover", cwd=tmp_path)
    scopes = json.loads(result.stdout.strip())
    assert "python" in scopes


def test_discover_emits_empty_when_no_triggers(tmp_path: Path):
    result = run_cli("--mode", "discover", cwd=tmp_path)
    scopes = json.loads(result.stdout.strip())
    assert scopes == []
