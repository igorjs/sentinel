"""Cross-ecosystem version ordering for selecting the minimum fix.

Sentinel targets crates.io, Go, and npm (all SemVer 2.0) via ``semver_key``
and PyPI (PEP 440) via ``pypi_key``. Both are backed by dedicated parsing
libraries (``semver`` and ``packaging`` respectively) rather than hand-rolled
regex, so they handle the full version syntax of each ecosystem correctly.

``semver_key`` strips a leading ``v`` (Go tags) and tolerates a missing
minor/patch component. ``pypi_key`` delegates entirely to
``packaging.version.Version``. Both collapse unparseable input to an internal
sentinel that sorts below every valid version so junk never masquerades as a
valid fix.
"""

from __future__ import annotations

import functools
from typing import Any

import semver
from packaging.version import InvalidVersion, Version


@functools.total_ordering
class _Key:
    """Orderable version key. ``_Key(None)`` sorts below any parsed version.

    Wraps a parsed ``packaging`` or ``semver`` version. Keys from different
    ecosystems must not be compared with each other; every call site sorts
    within a single ecosystem.
    """

    __slots__ = ("_parsed",)

    def __init__(self, parsed: Any) -> None:
        self._parsed = parsed

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _Key):
            return NotImplemented
        return self._parsed == other._parsed

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _Key):
            return NotImplemented
        if self._parsed is None:
            return other._parsed is not None
        if other._parsed is None:
            return False
        return self._parsed < other._parsed

    def __hash__(self) -> int:
        return hash(self._parsed)


def pypi_key(value: str) -> _Key:
    """Order a PyPI (PEP 440) version. Unparseable input sorts lowest."""
    try:
        return _Key(Version(value))
    except InvalidVersion:
        return _Key(None)


def semver_key(value: str) -> _Key:
    """Order a SemVer (crates/go/npm) version or freeform tag.

    Strips a leading ``v`` (Go tags) and tolerates a missing minor/patch.
    Unparseable input sorts lowest.
    """
    v = value.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    try:
        return _Key(semver.Version.parse(v, optional_minor_and_patch=True))
    except (ValueError, TypeError):
        return _Key(None)
