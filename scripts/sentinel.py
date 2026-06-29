"""sentinel CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import (
    scope_ci,
    scope_docker,
    scope_gh_release_pin,
    scope_go,
    scope_javascript,
    scope_python,
    scope_rust,
)
from scripts.config import Config, load_config, update_runtime_enabled
from scripts.osv import OsvCache

BUILTIN_SCOPES = {
    "rust": scope_rust,
    "go": scope_go,
    "javascript": scope_javascript,
    "python": scope_python,
    "ci": scope_ci,
    "docker": scope_docker,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel")
    parser.add_argument("--mode", required=True, choices=["discover", "run"])
    parser.add_argument("--scope", help="scope name (required for --mode run)")
    parser.add_argument("--config", default=".github/sentinel.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    config_path = workdir / args.config
    config = load_config(config_path if config_path.exists() else None)

    if args.mode == "discover":
        print(json.dumps(_discover(workdir, config)))
        return 0

    if not args.scope:
        parser.error("--scope is required for --mode run")
    return _run_scope(workdir, config, args.scope, dry_run=args.dry_run)


def _discover(workdir: Path, config: Config) -> list[str]:
    enabled: list[str] = []
    if _is_enabled(config, "rust") and (workdir / "Cargo.lock").exists():
        enabled.append("rust")
    gomod = workdir / _gomod_path(config)
    if _is_enabled(config, "go") and gomod.exists():
        enabled.append("go")
    if _is_enabled(config, "javascript") and (workdir / "package.json").exists():
        enabled.append("javascript")
    if _is_enabled(config, "python") and _has_python(workdir):
        enabled.append("python")
    if (
        _is_enabled(config, "docker")
        and update_runtime_enabled(config, "docker")
        and scope_docker.find_dockerfiles(workdir)
    ):
        enabled.append("docker")
    if (
        _is_enabled(config, "ci")
        and update_runtime_enabled(config, "ci")
        and scope_ci.find_workflows(workdir)
    ):
        enabled.append("ci")
    for custom in config.custom:
        enabled.append(custom.name)
    return enabled


def _is_enabled(config: Config, scope: str) -> bool:
    override = config.scopes.get(scope)
    return override.enabled if override else True


def _gomod_path(config: Config) -> str:
    override = config.scopes.get("go")
    return override.gomod_path if override and override.gomod_path else "go.mod"


def _has_python(workdir: Path) -> bool:
    return any(
        (workdir / f).exists()
        for f in (
            "pyproject.toml",
            "requirements.txt",
            "poetry.lock",
            "uv.lock",
            "Pipfile.lock",
        )
    )


def _run_scope(workdir: Path, config: Config, scope: str, *, dry_run: bool) -> int:
    if scope in BUILTIN_SCOPES:
        # scan_with_recovery also surfaces advisories suppressed in osv-scanner.toml
        # that now have a fix, so they can be bumped (and their suppression cleaned).
        osv = OsvCache.scan_with_recovery(workdir)
        results = BUILTIN_SCOPES[scope].run(workdir, config, osv, dry_run=dry_run)
    else:
        custom = next((c for c in config.custom if c.name == scope), None)
        if custom is None:
            print(f"unknown scope: {scope}", file=sys.stderr)
            return 2
        if custom.kind == "gh-release-pin":
            results = scope_gh_release_pin.run(
                workdir,
                Config(custom=[custom], defaults=config.defaults),
                OsvCache({"results": []}),
                dry_run=dry_run,
            )
        else:
            print(f"unknown custom kind: {custom.kind}", file=sys.stderr)
            return 2
    print(json.dumps([r.__dict__ for r in results], default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
