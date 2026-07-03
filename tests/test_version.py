from scripts.version import loose_tag_key, pypi_key, semver_key

# --- SemVer (crates / go / npm) ---


def test_semver_numeric_components_order_numerically():
    assert semver_key("1.2.9") < semver_key("1.2.10")


def test_semver_major_dominates():
    assert semver_key("2.0.0") > semver_key("1.9.9")


def test_semver_prerelease_sorts_below_release():
    assert semver_key("1.2.3-rc1") < semver_key("1.2.3")
    assert semver_key("1.0.0-alpha") < semver_key("1.0.0")


def test_semver_prerelease_ordering():
    assert semver_key("1.0.0-alpha") < semver_key("1.0.0-beta")
    assert semver_key("1.0.0-alpha.1") < semver_key("1.0.0-alpha.2")
    assert semver_key("1.0.0-1") < semver_key("1.0.0-alpha")


def test_semver_v_prefix_ignored():
    assert semver_key("v1.2.0") == semver_key("1.2.0")


def test_semver_build_metadata_ignored():
    assert semver_key("1.0.0+build.5") == semver_key("1.0.0")


def test_semver_optional_minor_and_patch():
    assert semver_key("1") == semver_key("1.0.0")
    assert semver_key("1.2") == semver_key("1.2.0")


def test_semver_unparseable_sorts_lowest():
    assert semver_key("not-a-version") < semver_key("0.0.1")


def test_semver_sorted_min_and_max():
    versions = ["1.2.3-rc1", "1.2.3", "1.10.0", "1.9.0"]
    ordered = sorted(versions, key=semver_key)
    assert ordered[0] == "1.2.3-rc1"
    assert ordered[-1] == "1.10.0"
    assert max(versions, key=semver_key) == "1.10.0"


# --- PyPI (PEP 440): the ordering the hand-rolled key got wrong ---


def test_pypi_non_hyphenated_prerelease_sorts_below_release():
    assert pypi_key("1.2.3rc1") < pypi_key("1.2.3")
    assert pypi_key("2.0.0a1") < pypi_key("2.0.0")


def test_pypi_dev_sorts_below_release():
    assert pypi_key("1.0.0.dev1") < pypi_key("1.0.0")


def test_pypi_post_sorts_above_release():
    assert pypi_key("1.0.0.post1") > pypi_key("1.0.0")


def test_pypi_epoch_dominates():
    assert pypi_key("2!1.0") > pypi_key("1.0")


def test_pypi_numeric_components_order_numerically():
    assert pypi_key("1.2.9") < pypi_key("1.2.10")


def test_pypi_unparseable_sorts_lowest():
    assert pypi_key("not-a-version") < pypi_key("0.0.1")


def test_pypi_sorted_prefers_lower_stable_over_prerelease():
    versions = ["1.26.5", "2.0.1", "2.0.0rc1"]
    ordered = sorted(versions, key=pypi_key)
    assert ordered[0] == "1.26.5"
    assert ordered[-1] == "2.0.1"


# --- semver_key >= / <= operators ---


def test_semver_key_ge_and_le_operators():
    assert semver_key("1.0.0") >= semver_key("1.0.0")
    assert semver_key("1.0.0") <= semver_key("1.0.0")
    assert semver_key("2.0.0") >= semver_key("1.0.0")


# --- loose_tag_key (gh-release-pin freeform tags) ---


def test_loose_tag_key_orders_calver_and_four_component():
    # The shapes semver_key rejects but the freeform-tag path must still order.
    assert loose_tag_key("2024.01.01") < loose_tag_key("2024.02.01")
    assert loose_tag_key("2024.01.01") != loose_tag_key("2024.02.01")
    assert loose_tag_key("1.2.3.4") > loose_tag_key("1.2.3.3")
    assert loose_tag_key("1.02.3") == loose_tag_key("1.2.3")


def test_loose_tag_key_v_prefix_and_prerelease_and_build():
    assert loose_tag_key("v1.2.0") == loose_tag_key("1.2.0")
    assert loose_tag_key("1.2.3-rc.1") < loose_tag_key("1.2.3")
    assert loose_tag_key("1.0.0+build.5") == loose_tag_key("1.0.0")


def test_loose_tag_key_no_digits_sorts_lowest():
    assert loose_tag_key("nightly") < loose_tag_key("0.0.1")
