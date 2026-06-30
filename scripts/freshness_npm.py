"""npm adapter for the freshness engine: list outdated deps, apply bumps."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.freshness import FreshnessError, Outdated, Selection

SCOPE = "javascript"
FILES_CHANGED = ["package.json", "package-lock.json"]


def _lock_versions(workdir: Path) -> dict[str, str]:
    try:
        data = json.loads((workdir / "package-lock.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise FreshnessError(f"unreadable package-lock.json: {e}") from e
    if not isinstance(data, dict):
        raise FreshnessError("package-lock.json: unexpected root type")
    out: dict[str, str] = {}
    for path, info in (data.get("packages") or {}).items():
        if path.startswith("node_modules/") and isinstance(info, dict) and info.get("version"):
            out[path[len("node_modules/") :]] = info["version"]
    return out


def list_outdated(workdir: Path) -> list[Outdated]:
    if not (workdir / "package-lock.json").exists():
        return []
    try:
        proc = subprocess.run(
            ["npm", "outdated", "--json"], cwd=workdir, capture_output=True, text=True
        )
    except OSError as e:
        raise FreshnessError(f"npm not available: {e}") from e
    # npm outdated exits 1 when there are outdated packages, 0 when none.
    if proc.returncode not in (0, 1):
        raise FreshnessError(f"npm outdated failed (exit {proc.returncode}): {proc.stderr.strip()}")
    text = proc.stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FreshnessError(f"npm outdated returned non-JSON: {e}") from e
    if not isinstance(data, dict):
        raise FreshnessError("npm outdated: unexpected root type")
    lockv = _lock_versions(workdir)
    out: list[Outdated] = []
    for name, info in data.items():
        if isinstance(info, list):
            info = info[0] if info else {}
        if not isinstance(info, dict):
            continue
        wanted = info.get("wanted")
        latest = info.get("latest")
        current = info.get("current") or lockv.get(name)
        if not (current and wanted and latest):
            continue
        out.append(Outdated(name=name, current=current, wanted=wanted, latest=latest))
    return sorted(out, key=lambda o: o.name)


def _run_npm(cmd: list[str], workdir: Path) -> None:
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    except OSError as e:
        raise FreshnessError(f"npm not available: {e}") from e
    if proc.returncode != 0:
        raise FreshnessError(
            f"{' '.join(cmd)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )


_DEP_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _bump_manifest(workdir: Path, majors: list[Selection]) -> None:
    path = workdir / "package.json"
    try:
        raw = path.read_text()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        raise FreshnessError(f"unreadable package.json: {e}") from e
    text = raw
    for sel in majors:
        oldspec = None
        for section in _DEP_SECTIONS:
            deps = data.get(section) or {}
            if sel.name in deps:
                oldspec = deps[sel.name]
                break
        if oldspec is None:
            continue  # constraint not locatable -> skip this dep
        needle = f'"{sel.name}": "{oldspec}"'
        repl = f'"{sel.name}": "^{sel.target}"'
        if needle in text:
            text = text.replace(needle, repl, 1)
    if text != raw:
        try:
            path.write_text(text)
        except OSError as e:
            raise FreshnessError(f"cannot write package.json: {e}") from e


def apply(workdir: Path, selections: list[Selection]) -> None:
    in_range = [s for s in selections if not s.is_major]
    majors = [s for s in selections if s.is_major]
    if in_range:
        names = [s.name for s in in_range]
        _run_npm(["npm", "update", *names, "--package-lock-only", "--ignore-scripts"], workdir)
    if majors:
        _bump_manifest(workdir, majors)
        _run_npm(["npm", "install", "--package-lock-only", "--ignore-scripts"], workdir)
