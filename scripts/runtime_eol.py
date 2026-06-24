"""endoflife.date client and runtime version-string math.

Pure stdlib. Network access (fetch_cycles) is isolated and fail-closed; all
version parsing is pure and injectable for tests.
"""

from __future__ import annotations

import re

_FLOOR_RE = re.compile(r">=\s*([0-9]+(?:\.[0-9]+)*)")
_NUMERIC_RE = re.compile(r"^([vV]?)([0-9]+(?:\.[0-9]+)*)$")


def floor_lower_cycle(spec: str, *, parts: int) -> str | None:
    """Cycle from the '>=' lower bound of a floor spec. None if no '>=' bound."""
    m = _FLOOR_RE.search(spec or "")
    if not m:
        return None
    return ".".join(m.group(1).split(".")[:parts])


def bump_floor(spec: str, target_cycle: str) -> str:
    """Replace the first '>=' version with target_cycle, preserving the rest."""
    return _FLOOR_RE.sub(lambda m: m.group(0).replace(m.group(1), target_cycle, 1), spec, count=1)


def pin_cycle(text: str, *, parts: int) -> str | None:
    """Cycle from a pin-file value ('3.8.10', 'v18', ...). None if non-numeric."""
    m = _NUMERIC_RE.match((text or "").strip())
    if not m:
        return None
    return ".".join(m.group(2).split(".")[:parts])


def bump_pin(text: str, target_cycle: str, target_latest: str, *, parts: int) -> str:
    """Rewrite a pin value, matching its original granularity and 'v' prefix."""
    m = _NUMERIC_RE.match((text or "").strip())
    if not m:
        raise ValueError(f"unparseable pin value: {text!r}")
    prefix = m.group(1)
    has_patch = len(m.group(2).split(".")) > parts
    return f"{prefix}{target_latest if has_patch else target_cycle}"
