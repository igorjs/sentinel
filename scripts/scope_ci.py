"""ci scope: bump end-of-life python/node version-matrix entries in GitHub workflows."""

from __future__ import annotations

from scripts.runtime_eol import bump_pin, eol_target, pin_cycle

SCOPE = "ci"

# matrix key -> (endoflife product, cycle granularity, LTS-only targets)
_MATRIX_KEYS: dict[str, tuple[str, int, bool]] = {
    "python-version": ("python", 2, False),
    "node-version": ("nodejs", 1, True),
}


def _reclothe(original: object, new_str: str) -> object | None:
    """Return new_str dressed in original's scalar style, or None if it can't be."""
    from ruamel.yaml.scalarstring import ScalarString

    if isinstance(original, ScalarString):
        return type(original)(new_str)  # preserve quote/style
    if isinstance(original, bool):
        return None
    if isinstance(original, int):
        try:
            return int(new_str)
        except ValueError:
            return None
    if isinstance(original, str):
        return new_str
    return None  # float / other -> leave untouched


def bump_matrix_list(seq, cfg, *, today, lead_days, cycles) -> bool:
    _, parts, lts_only = cfg
    changed = False
    for i in range(len(seq)):
        s = str(seq[i])
        cycle = pin_cycle(s, parts=parts)
        if cycle is None:
            continue
        target = eol_target(cycles, cycle, today=today, lead_days=lead_days, lts_only=lts_only)
        if target is None:
            continue
        target_cycle, target_latest = target
        new_str = bump_pin(s, target_cycle, target_latest, parts=parts)
        if new_str == s:
            continue
        new_val = _reclothe(seq[i], new_str)
        if new_val is None:
            continue
        seq[i] = new_val
        changed = True
    if changed:
        seen: set[str] = set()
        i = 0
        while i < len(seq):
            key = str(seq[i])
            if key in seen:
                del seq[i]
            else:
                seen.add(key)
                i += 1
    return changed
