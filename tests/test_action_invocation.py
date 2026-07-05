"""Guards the way the composite actions launch the CLI.

The action.yml files used to run the CLI by file path
(`python <action_path>/scripts/sentinel.py`). That puts `scripts/` on
`sys.path[0]`, which (1) shadows the stdlib `types` module with our
`scripts/types.py` and (2) breaks the `from scripts import ...` package imports.
The unit suite missed it because pytest and tests/test_sentinel_cli.py invoke
via `-m`, never by file path. These tests pin the working invocation so the bug
cannot return.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ACTION = _PROJECT_ROOT / "action.yml"
_DISCOVER_ACTION = _PROJECT_ROOT / "discover" / "action.yml"
_SCRIPTS = _PROJECT_ROOT / "scripts"


def test_no_script_shadows_a_stdlib_module():
    # A file-path invocation puts scripts/ on sys.path[0]; any scripts/<name>.py
    # whose stem matches a stdlib top-level module (e.g. types.py) is then
    # imported instead of the stdlib one, breaking the interpreter. Keep scripts/
    # clear of such names so the footgun can't reappear.
    offenders = sorted(p.stem for p in _SCRIPTS.glob("*.py") if p.stem in sys.stdlib_module_names)
    assert offenders == [], (
        f"scripts/ files shadow stdlib modules {offenders}; rename them "
        "(e.g. types.py -> models.py)."
    )


def test_run_action_invokes_cli_as_module():
    text = _ACTION.read_text()
    assert "python -m scripts.sentinel" in text, (
        "action.yml must invoke the CLI as a module; file-path invocation puts "
        "scripts/ on sys.path[0] and shadows stdlib `types`."
    )
    assert "sentinel.py" not in text, (
        "action.yml still invokes the CLI by file path (sentinel.py); use "
        "`python -m scripts.sentinel` instead."
    )


def test_discover_action_invokes_cli_as_module():
    text = _DISCOVER_ACTION.read_text()
    assert "python -m scripts.sentinel" in text, (
        "discover/action.yml must invoke the CLI as a module."
    )
    assert "sentinel.py" not in text, (
        "discover/action.yml still invokes the CLI by file path (sentinel.py)."
    )


def test_action_passes_inputs_via_env_not_shell_interpolation():
    text = _ACTION.read_text()
    # Inputs reach the CLI through env vars, never interpolated into the shell
    # command (that would let a caller inject shell via a malicious input).
    assert '--scope "$SCOPE"' in text
    assert '--config "$CONFIG_PATH"' in text
    assert '--scope "${{ inputs.scope }}"' not in text
    assert '--config "${{ inputs.config_path }}"' not in text
    # dry_run is the most injection-sensitive input (it lands in an `if [[ ]]`).
    assert '"$DRY_RUN" == "true"' in text
    assert '"${{ inputs.dry_run }}" == "true"' not in text


def test_discover_action_passes_config_via_env_and_heredoc():
    text = _DISCOVER_ACTION.read_text()
    assert '--config "$CONFIG_PATH"' in text
    assert '--config "${{ inputs.config_path }}"' not in text
    assert "scopes<<" in text  # heredoc GITHUB_OUTPUT write, not a single-line echo


def test_cli_runs_as_module_from_action_root_without_pythonpath(tmp_path: Path):
    # Mirror the action's exact mechanism: cwd is the action root and PYTHONPATH
    # is unset, so success depends solely on `-m` adding the action root to
    # sys.path. tests/test_sentinel_cli.py sets PYTHONPATH and so cannot catch a
    # regression in this path.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.sentinel",
            "--mode",
            "discover",
            "--workdir",
            str(tmp_path),
        ],
        capture_output=True,
        check=True,
        text=True,
        cwd=_PROJECT_ROOT,
        env=env,
    )
    assert json.loads(result.stdout.strip()) == []
