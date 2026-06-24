"""Wrapper around `osv-scanner` with an in-process cache.

Parses `--format json` output (`results[].packages[].vulnerabilities[]`).
Severity in osv-scanner v2.x lives in `packages[].groups[].max_severity` (a
numeric CVSS score), exposed via `max_severity`. `scan_with_recovery` re-scans
without the repo's `osv-scanner.toml` ignores so an advisory that was suppressed
but now has a fix can still be bumped (and its suppression cleaned).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

_NOT_FOUND_MSG = (
    "osv-scanner not found on PATH. The sentinel action installs it automatically; "
    "if you are running sentinel locally, install osv-scanner first "
    "(https://github.com/google/osv-scanner)."
)


class OsvCache:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def scan(cls, workdir: Path) -> OsvCache:
        return cls(_raw_scan(workdir))

    @classmethod
    def scan_with_recovery(cls, workdir: Path) -> OsvCache:
        """Normal scan plus any advisory suppressed in osv-scanner.toml that now
        has a fix available. The suppressed-but-fixable advisories are recovered
        via a second scan that bypasses the repo's ignore config and merged into
        the results, so they flow through the normal bump path (which also strips
        the now-removable suppression)."""
        data = _raw_scan(workdir)
        toml_path = workdir / "osv-scanner.toml"
        if toml_path.exists():
            suppressed = parse_ignored_ids(toml_path.read_text())
            if suppressed:
                recovered = _recovered_packages(_raw_scan(workdir, bypass_ignores=True), suppressed)
                if recovered:
                    data.setdefault("results", []).append({"packages": recovered})
        return cls(data)

    def advisories(self, ecosystem: str, package: str | None = None) -> list[dict[str, Any]]:
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

    def max_severity(self, advisory_id: str) -> float | None:
        """Numeric CVSS score for an advisory, from osv-scanner v2 `groups[].max_severity`.

        Returns None when the scanner reported no score (e.g. v1.x output, or an
        advisory with no CVSS data) so callers fall back / treat it as unknown.
        """
        for r in self._data.get("results", []):
            for p in r.get("packages", []):
                for g in p.get("groups", []):
                    if advisory_id in g.get("ids", []) or advisory_id in g.get("aliases", []):
                        raw = g.get("max_severity")
                        if raw:
                            try:
                                return float(raw)
                            except ValueError:
                                return None
        return None


def _raw_scan(workdir: Path, *, bypass_ignores: bool = False) -> dict[str, Any]:
    cmd = ["osv-scanner", "--format", "json", "--recursive", str(workdir)]
    empty_cfg = None
    if bypass_ignores:
        # An explicit --config overrides auto-discovery of the repo's
        # osv-scanner.toml, so an empty config makes the scan report everything,
        # including advisories the repo suppressed.
        fd, empty_cfg = tempfile.mkstemp(suffix=".toml")
        os.close(fd)
        cmd += ["--config", empty_cfg]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(_NOT_FOUND_MSG) from e
    finally:
        if empty_cfg:
            os.unlink(empty_cfg)
    if result.returncode == 128:
        # osv-scanner exit 128 = "no package sources found": the scope resolved
        # (e.g. a pyproject.toml exists) but there's no lockfile/manifest to scan.
        # That's benign — nothing to scan means no advisories, not a failure.
        return {"results": []}
    if result.returncode not in (0, 1):
        raise RuntimeError(f"osv-scanner failed (exit {result.returncode}): {result.stderr}")
    return json.loads(result.stdout or '{"results": []}')


def parse_ignored_ids(osv_scanner_toml: str) -> set[str]:
    """Advisory ids from the [[IgnoredVulns]] blocks of an osv-scanner.toml."""
    try:
        data = tomllib.loads(osv_scanner_toml)
    except tomllib.TOMLDecodeError:
        return set()
    return {
        e["id"]
        for e in data.get("IgnoredVulns", [])
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    }


def _recovered_packages(
    audit_data: dict[str, Any], suppressed_ids: set[str]
) -> list[dict[str, Any]]:
    """Package entries from a bypass scan, reduced to their suppressed vulns.

    Keeps each package's `groups` so severity lookup still resolves; drops
    packages with no suppressed vuln so non-suppressed findings aren't duplicated.
    """
    out: list[dict[str, Any]] = []
    for r in audit_data.get("results", []):
        for p in r.get("packages", []):
            kept = [v for v in p.get("vulnerabilities", []) if v.get("id") in suppressed_ids]
            if kept:
                out.append({**p, "vulnerabilities": kept})
    return out


def from_fixture(path: Path) -> OsvCache:
    return OsvCache(json.loads(path.read_text()))


def _has_fix(adv: dict[str, Any]) -> bool:
    return any(
        "fixed" in event
        for a in adv.get("affected", [])
        for r in a.get("ranges", [])
        for event in r.get("events", [])
    )
