import pytest

from scripts.models import Drift
from scripts.severity import (
    SEVERITY_ORDER,
    band_for_score,
    cvss_base_score,
    derive_severity,
    gate,
    meets_threshold,
    normalize_label,
    severity_line,
)


@pytest.mark.parametrize(
    "vector,expected",
    [
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H", 7.5),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
        ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L", 3.7),
    ],
)
def test_cvss_base_score_matches_nvd(vector, expected):
    assert cvss_base_score(vector) == expected


def test_cvss_base_score_v4_or_garbage_returns_none():
    assert cvss_base_score("CVSS:4.0/AV:N/AC:L/...") is None
    assert cvss_base_score("not-a-vector") is None
    assert cvss_base_score("CVSS:3.1/AV:Z") is None  # bad metric value


def test_band_for_score_boundaries():
    assert band_for_score(0.0) == "none"
    assert band_for_score(0.1) == "low"
    assert band_for_score(3.9) == "low"
    assert band_for_score(4.0) == "medium"
    assert band_for_score(6.9) == "medium"
    assert band_for_score(7.0) == "high"
    assert band_for_score(8.9) == "high"
    assert band_for_score(9.0) == "critical"
    assert band_for_score(10.0) == "critical"


def test_severity_order_is_ascending():
    assert SEVERITY_ORDER == ["none", "low", "medium", "high", "critical"]


def test_normalize_label_maps_moderate_to_medium():
    assert normalize_label("MODERATE") == "medium"
    assert normalize_label("High") == "high"
    assert normalize_label("nonsense") is None


def test_derive_severity_prefers_cvss_vector():
    adv = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
    }
    assert derive_severity(adv) == "critical"


def test_derive_severity_takes_highest_band_among_vectors():
    adv = {
        "severity": [
            {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L"},  # 3.7 low
            {
                "type": "CVSS_V3",
                "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H",
            },  # 7.5 high
        ]
    }
    assert derive_severity(adv) == "high"


def test_derive_severity_falls_back_to_label_when_no_parsable_vector():
    adv = {
        "severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N/..."}],
        "database_specific": {"severity": "MODERATE"},
    }
    assert derive_severity(adv) == "medium"


def test_derive_severity_unknown_when_nothing_usable():
    assert derive_severity({}) == "unknown"
    assert derive_severity({"database_specific": {"severity": "weird"}}) == "unknown"


def test_meets_threshold_none_means_no_gating():
    assert meets_threshold("low", None) is True


def test_meets_threshold_unknown_acts_fail_open():
    assert meets_threshold("unknown", "critical") is True


def test_meets_threshold_rank_compare():
    assert meets_threshold("high", "medium") is True
    assert meets_threshold("low", "high") is False
    assert meets_threshold("high", "high") is True


def test_gate_keeps_and_counts():
    drifts = [
        Drift(scope="x", key="a", summary="", fixed_versions=[], current="", severity="low"),
        Drift(scope="x", key="b", summary="", fixed_versions=[], current="", severity="high"),
        Drift(scope="x", key="c", summary="", fixed_versions=[], current="", severity="unknown"),
    ]
    kept, skipped = gate(drifts, "high")
    assert [d.key for d in kept] == ["b", "c"]  # high passes, unknown fails-open
    assert skipped == 1


def test_severity_line_discloses_unknown():
    assert severity_line("high") == "**Severity:** high"
    assert "bumping anyway" in severity_line("unknown")


def test_derive_severity_uses_provided_score():
    # osv-scanner v2.4.0 supplies a precomputed numeric score (groups[].max_severity).
    assert derive_severity({}, score=8.6) == "high"
    assert derive_severity({}, score=9.1) == "critical"
    assert derive_severity({}, score=0.0) == "none"


def test_derive_severity_score_takes_precedence_over_vector():
    adv = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:L"}]
    }
    assert derive_severity(adv, score=9.8) == "critical"  # explicit score wins over v1 vector


def test_derive_severity_falls_back_to_vector_when_no_score():
    adv = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
    }
    assert derive_severity(adv) == "critical"  # v1.x fallback still works
    assert derive_severity({}) == "unknown"
