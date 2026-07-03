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

gh-release-pin freeform upstream tags use ``loose_tag_key``, which orders by
numeric release components so it tolerates zero-padded CalVer (``2024.01.01``),
4-component versions, and other non-SemVer shapes that real projects tag with.
"""

from __future__ import annotations

import functools
import re
from typing import Any

import semver
from packaging.version import InvalidVersion, Version

_DIGITS = re.compile(r"\d+")


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


def loose_tag_key(value: str) -> _Key:
    """Order a freeform upstream release tag leniently (gh-release-pin).

    Upstream repos tag releases in varied schemes: strict SemVer, zero-padded
    CalVer (``2024.01.01``), 4-component, etc. Strict SemVer parsing rejects the
    non-SemVer numeric shapes and would treat them as unorderable, so this path
    orders by numeric release components instead, demoting a ``-``-delimited
    prerelease below its release. Tags with no digits sort lowest. Trades
    precise SemVer prerelease precedence for tolerance of real release-tag
    shapes; only gh-release-pin uses it, so its keys are never compared against
    pypi_key / semver_key keys.
    """
    v = value.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    v = v.split("+", 1)[0]  # drop build metadata
    release_s, sep, pre_s = v.partition("-")
    release = tuple(int(x) for x in _DIGITS.findall(release_s))
    if not release:
        return _Key(None)
    pre = (1,) if not sep else (0, pre_s)
    return _Key((release, pre))
