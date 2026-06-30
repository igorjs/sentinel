"""Version-freshness engine: select outdated deps and open grouped PRs.

The per-ecosystem adapter (injected) does the package-manager work; this module
owns policy (level, include/exclude), grouping, PR/issue shaping, and fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from scripts.version import version_key


class FreshnessError(RuntimeError):
    """A package manager was unavailable, or returned unusable data."""


@dataclass(frozen=True)
class Outdated:
    name: str
    current: str
    wanted: str  # latest within the declared range
    latest: str  # absolute latest stable


@dataclass(frozen=True)
class Selection:
    name: str
    current: str
    target: str
    is_major: bool


def _vgt(a: str, b: str) -> bool:
    """True when version a sorts strictly above version b."""
    return version_key(a) > version_key(b)


def select(
    outdated: list[Outdated],
    *,
    level: str,
    include: list[str],
    exclude: list[str],
) -> list[Selection]:
    """Pick a bump target per dep, honouring level and include/exclude globs."""
    out: list[Selection] = []
    for o in outdated:
        if include and not any(fnmatch(o.name, pat) for pat in include):
            continue
        if any(fnmatch(o.name, pat) for pat in exclude):
            continue
        target, is_major = o.wanted, False
        if level == "major" and _vgt(o.latest, o.wanted):
            target, is_major = o.latest, True
        if target == o.current:
            continue
        out.append(Selection(name=o.name, current=o.current, target=target, is_major=is_major))
    return sorted(out, key=lambda s: s.name)
