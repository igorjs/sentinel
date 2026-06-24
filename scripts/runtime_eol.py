"""endoflife.date client and runtime version-string math.

Pure stdlib. Network access (fetch_cycles) is isolated and fail-closed; all
version parsing is pure and injectable for tests.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date

_FLOOR_RE = re.compile(r">=\s*([0-9]+(?:\.[0-9]+)*)")
_NUMERIC_RE = re.compile(r"^([vV]?)([0-9]+(?:\.[0-9]+)*)$")
_CYCLE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


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


def _cycle_key(cycle: str) -> tuple[int, ...]:
    return tuple(int(p) for p in cycle.split("."))


def _eol_status(raw_eol) -> tuple[str, date | None]:
    """Classify an endoflife `eol` field. Returns one of:
    ("eol", None)     already end-of-life (boolean true)
    ("none", None)    no end-of-life date (false/absent)
    ("date", d)       a parsed ISO date
    ("invalid", None) an unparseable/unexpected value (treated conservatively)
    """
    if raw_eol is True:
        return ("eol", None)
    if raw_eol is False or raw_eol is None:
        return ("none", None)
    if isinstance(raw_eol, str):
        try:
            return ("date", date.fromisoformat(raw_eol))
        except ValueError:
            return ("invalid", None)
    return ("invalid", None)


def _eol_passed_or_within(raw_eol, *, today: date, lead_days: int) -> bool:
    kind, eol = _eol_status(raw_eol)
    if kind == "eol":
        return True
    if kind == "date":
        return (today.toordinal() + lead_days) >= eol.toordinal()
    return False  # "none" or "invalid": not in window


def _supported(raw_eol, *, today: date, lead_days: int) -> bool:
    kind, eol = _eol_status(raw_eol)
    if kind == "none":
        return True
    if kind == "date":
        return eol.toordinal() > (today.toordinal() + lead_days)
    return False  # "eol" or "invalid": not a safe target


def _is_lts_even(entry: dict) -> bool:
    if not entry.get("lts"):
        return False
    try:
        return int(entry["cycle"].split(".")[0]) % 2 == 0
    except (ValueError, IndexError):
        return False


def eol_target(
    cycles: list[dict],
    current_cycle: str,
    *,
    today: date,
    lead_days: int,
    lts_only: bool,
) -> tuple[str, str] | None:
    """(target_cycle, target_latest) if current_cycle is EOL/within lead_days; else None.

    Target = oldest still-supported cycle strictly newer than current_cycle
    (LTS even-major only when lts_only).
    """
    cycles = [c for c in cycles if isinstance(c.get("cycle"), str) and _CYCLE_RE.match(c["cycle"])]
    by_cycle = {c["cycle"]: c for c in cycles}
    current = by_cycle.get(current_cycle)
    if current is None:
        return None
    if not _eol_passed_or_within(current.get("eol"), today=today, lead_days=lead_days):
        return None
    cur_key = _cycle_key(current_cycle)
    candidates = [
        c
        for c in cycles
        if _cycle_key(c["cycle"]) > cur_key
        and _supported(c.get("eol"), today=today, lead_days=lead_days)
        and (not lts_only or _is_lts_even(c))
    ]
    if not candidates:
        return None
    target = min(candidates, key=lambda c: _cycle_key(c["cycle"]))
    return target["cycle"], str(target.get("latest", target["cycle"]))


_API = "https://endoflife.date/api/{product}.json"


class RuntimeEolError(RuntimeError):
    """endoflife.date was unreachable or returned unusable data."""


def fetch_cycles(product: str, *, timeout: float = 10.0) -> list[dict]:
    url = _API.format(product=product)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeEolError(f"endoflife.date fetch failed for {product}: {e}") from e
    if not isinstance(data, list):
        raise RuntimeEolError(f"endoflife.date returned non-list for {product}")
    return data
