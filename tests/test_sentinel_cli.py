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
        capture_output=True,
        check=True,
        text=True,
        cwd=cwd,
        env=env,
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


def test_discover_emits_docker_only_when_opted_in(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.8\n")
    # default config -> docker NOT discovered (opt-in)
    result = run_cli("--mode", "discover", cwd=tmp_path)
    assert "docker" not in json.loads(result.stdout.strip())

    cfg = tmp_path / ".github" / "sentinel.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[scopes.docker]\nupdate_runtime = true\n")
    result = run_cli("--mode", "discover", "--config", ".github/sentinel.toml", cwd=tmp_path)
    assert "docker" in json.loads(result.stdout.strip())


def test_discover_no_docker_without_dockerfile(tmp_path: Path):
    cfg = tmp_path / ".github" / "sentinel.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[scopes.docker]\nupdate_runtime = true\n")
    result = run_cli("--mode", "discover", "--config", ".github/sentinel.toml", cwd=tmp_path)
    assert "docker" not in json.loads(result.stdout.strip())


def test_discover_emits_ci_only_when_opted_in(tmp_path: Path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n")
    # default config -> ci NOT discovered (opt-in)
    result = run_cli("--mode", "discover", cwd=tmp_path)
    assert "ci" not in json.loads(result.stdout.strip())

    cfg = tmp_path / "sentinel.toml"
    cfg.write_text("[scopes.ci]\nupdate_runtime = true\n")
    result = run_cli("--mode", "discover", "--config", "sentinel.toml", cwd=tmp_path)
    assert "ci" in json.loads(result.stdout.strip())


def test_discover_emits_ci_for_runs_on_only_workflow(tmp_path: Path):
    """ci is discovered when a workflow file exists and update_runtime is opted in (file-presence gating, not content-based).

    Note: runner-OS content handling (actual bump of a runs-on-only workflow) is tested in test_scope_ci.py::test_scan_runs_on_only_workflow.
    This CLI test verifies discovery is gated on workflow file presence + update_runtime opt-in.
    The realistic no-matrix runs-on shape adds nuance over the generic "on: push" stub.
    """
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "on: push\njobs:\n  build:\n    runs-on: ubuntu-20.04\n    steps:\n      - run: echo x\n"
    )
    # default config -> ci NOT discovered (opt-in required)
    result = run_cli("--mode", "discover", cwd=tmp_path)
    assert "ci" not in json.loads(result.stdout.strip())

    cfg = tmp_path / "sentinel.toml"
    cfg.write_text("[scopes.ci]\nupdate_runtime = true\n")
    result = run_cli("--mode", "discover", "--config", "sentinel.toml", cwd=tmp_path)
    assert "ci" in json.loads(result.stdout.strip())


def test_discover_no_ci_without_workflows(tmp_path: Path):
    cfg = tmp_path / "sentinel.toml"
    cfg.write_text("[scopes.ci]\nupdate_runtime = true\n")
    result = run_cli("--mode", "discover", "--config", "sentinel.toml", cwd=tmp_path)
    assert "ci" not in json.loads(result.stdout.strip())
