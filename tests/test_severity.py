import pytest

from scripts.severity import SEVERITY_ORDER, band_for_score, cvss_base_score


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
