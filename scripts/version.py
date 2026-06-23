"""Cross-ecosystem version ordering for selecting the minimum fix.

Sentinel targets crates.io, Go, and npm (all SemVer 2.0) plus PyPI (PEP 440). A
single sort key handles the realistic shapes of advisory "fixed" versions across
them:

- numeric release components compared numerically (``1.2.9`` < ``1.2.10``);
- an optional ``v`` prefix (Go tags) stripped;
- a prerelease suffix that sorts *below* the corresponding release, with numeric
  identifiers ranking below alphanumeric ones (the SemVer precedence rule, which
  also matches PEP 440 ordering for the common cases);
- build metadata (after ``+``) ignored, per SemVer.

Unparseable input collapses to an empty release tuple, which sorts lowest, so
junk never masquerades as a valid (higher) fix version.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+")


def _prerelease_key(pre: str) -> tuple:
    parts = []
    for ident in re.split(r"[.\-]", pre):
        if ident.isdigit():
            parts.append((0, int(ident), ""))  # numeric: lowest precedence
        else:
            parts.append((1, 0, ident))  # alphanumeric: compared lexically
    return tuple(parts)


def version_key(value: str) -> tuple:
    """Return a sort key ordering ``value`` against other version strings."""
    v = value.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    v = v.split("+", 1)[0]  # drop build metadata
    release_s, _, pre_s = v.partition("-")
    release = tuple(int(x) for x in _NUM.findall(release_s))
    # A release with no prerelease outranks the same release with one.
    pre = (1,) if pre_s == "" else (0, *_prerelease_key(pre_s))
    return (release, pre)
