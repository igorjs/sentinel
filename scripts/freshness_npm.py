"""npm adapter for the freshness engine: list outdated deps, apply bumps."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.freshness import FreshnessError, Outdated

SCOPE = "javascript"
FILES_CHANGED = ["package.json", "package-lock.json"]


def _lock_versions(workdir: Path) -> dict[str, str]:
    try:
        data = json.loads((workdir / "package-lock.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise FreshnessError(f"unreadable package-lock.json: {e}") from e
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
