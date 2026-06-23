from scripts.version import version_key


def test_numeric_components_order_numerically_not_lexically():
    assert version_key("1.2.9") < version_key("1.2.10")


def test_major_dominates():
    assert version_key("2.0.0") > version_key("1.9.9")


def test_prerelease_sorts_below_its_release():
    assert version_key("1.2.3-rc1") < version_key("1.2.3")
    assert version_key("1.0.0-alpha") < version_key("1.0.0")


def test_prerelease_ordering():
    assert version_key("1.0.0-alpha") < version_key("1.0.0-beta")
    assert version_key("1.0.0-alpha.1") < version_key("1.0.0-alpha.2")
    # Numeric identifiers have lower precedence than alphanumeric (SemVer rule).
    assert version_key("1.0.0-1") < version_key("1.0.0-alpha")


def test_v_prefix_is_ignored():
    assert version_key("v1.2.0") == version_key("1.2.0")


def test_build_metadata_is_ignored():
    assert version_key("1.0.0+build.5") == version_key("1.0.0")
    assert version_key("1.0.0+exp.sha.5114f85") == version_key("1.0.0")


def test_sorted_picks_correct_min_and_max():
    versions = ["1.2.10", "1.2.9", "1.10.0", "1.2.3-rc1", "1.2.3"]
    ordered = sorted(versions, key=version_key)
    assert ordered[0] == "1.2.3-rc1"
    assert ordered[-1] == "1.10.0"
    assert max(versions, key=version_key) == "1.10.0"


def test_unparseable_sorts_lowest():
    assert version_key("not-a-version") < version_key("0.0.1")
