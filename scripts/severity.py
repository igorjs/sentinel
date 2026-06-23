"""Derive one comparable severity per OSV advisory and gate by a threshold.

Pure functions, no I/O. CVSS v3.0/v3.1 base scores are computed from the vector
string (the OSV `severity[].score` field is a vector, not a number). v4-only or
unparseable vectors return None so callers fall back to the qualitative label.
"""

from __future__ import annotations

import math

SEVERITY_ORDER = ["none", "low", "medium", "high", "critical"]

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
_AC = {"L": 0.77, "H": 0.44}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.00}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}


def cvss_base_score(vector: str) -> float | None:
    if not vector.startswith(("CVSS:3.0", "CVSS:3.1")):
        return None
    metrics: dict[str, str] = {}
    for part in vector.split("/")[1:]:
        if ":" not in part:
            return None
        k, v = part.split(":", 1)
        metrics[k] = v
    try:
        av = _AV[metrics["AV"]]
        ac = _AC[metrics["AC"]]
        ui = _UI[metrics["UI"]]
        c = _CIA[metrics["C"]]
        i = _CIA[metrics["I"]]
        a = _CIA[metrics["A"]]
        scope_changed = metrics["S"] == "C"
        pr = (_PR_CHANGED if scope_changed else _PR_UNCHANGED)[metrics["PR"]]
    except KeyError:
        return None
    isc_base = 1 - ((1 - c) * (1 - i) * (1 - a))
    if scope_changed:
        impact = 7.52 * (isc_base - 0.029) - 3.25 * (isc_base - 0.02) ** 15
    else:
        impact = 6.42 * isc_base
    if impact <= 0:
        return 0.0
    exploit = 8.22 * av * ac * pr * ui
    raw = 1.08 * (impact + exploit) if scope_changed else impact + exploit
    score = min(raw, 10.0)
    if vector.startswith("CVSS:3.0"):
        return math.ceil(score * 10) / 10
    return _roundup(score)


def _roundup(x: float) -> float:
    n = round(x * 100000)
    if n % 10000 == 0:
        return n / 100000
    return (math.floor(n / 10000) + 1) / 10


def band_for_score(score: float) -> str:
    if score <= 0.0:
        return "none"
    if score < 4.0:
        return "low"
    if score < 7.0:
        return "medium"
    if score < 9.0:
        return "high"
    return "critical"
