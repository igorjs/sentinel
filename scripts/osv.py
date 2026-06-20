"""Wrapper around `osv-scanner` with in-process cache."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class OsvCache:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def scan(cls, workdir: Path) -> OsvCache:
        cmd = ["osv-scanner", "--format", "json", "--recursive", str(workdir)]
        result = subprocess.run(cmd, capture_output=True, check=False, text=True)
        if result.returncode not in (0, 1):
            raise RuntimeError(
                f"osv-scanner failed (exit {result.returncode}): {result.stderr}"
            )
        return cls(json.loads(result.stdout or '{"results": []}'))

    def advisories(
        self, ecosystem: str, package: str | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self._data.get("results", []):
            for p in r.get("packages", []):
                pkg_eco = p.get("package", {}).get("ecosystem")
                pkg_name = p.get("package", {}).get("name")
                if pkg_eco != ecosystem:
                    continue
                if package is not None and pkg_name != package:
                    continue
                out.extend(p.get("vulnerabilities", []))
        return out

    def fixable_advisories(self, ecosystem: str) -> list[dict[str, Any]]:
        return [a for a in self.advisories(ecosystem) if _has_fix(a)]


def from_fixture(path: Path) -> OsvCache:
    return OsvCache(json.loads(path.read_text()))


def _has_fix(adv: dict[str, Any]) -> bool:
    return any(
        "fixed" in event
        for a in adv.get("affected", [])
        for r in a.get("ranges", [])
        for event in r.get("events", [])
    )
