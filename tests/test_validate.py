import pytest

from scripts.validate import UnsafeIdentifier, ensure_safe, is_safe_arg


@pytest.mark.parametrize(
    "value",
    [
        "tokio",
        "serde_json",
        "foo-bar",
        "1.2.3",
        "v1.2.3",
        "v0.0.0-20210101120000-abcdef123456",  # go pseudo-version
        "github.com/foo/bar",  # go module path
        "@scope/pkg",  # npm scoped package
        "1.2.3.post1",  # PyPI post-release
        "2.0.0-rc.1",  # prerelease
        "1.0.0+build.5",  # build metadata
    ],
)
def test_is_safe_arg_accepts_legitimate_tokens(value):
    assert is_safe_arg(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "-rf",  # leading dash → argument injection
        "--config=/etc/passwd",
        "-O/tmp/x",
        "foo bar",  # whitespace
        "foo;rm -rf /",  # shell metacharacters
        "foo$(whoami)",
        "foo`id`",
        "foo|cat",
        "foo&background",
        "foo\nbar",  # newline / control char
        "foo>out",
    ],
)
def test_is_safe_arg_rejects_dangerous_tokens(value):
    assert is_safe_arg(value) is False


def test_ensure_safe_passes_through_safe_values():
    # Returns None and does not raise.
    assert ensure_safe("tokio", "1.2.3") is None


def test_ensure_safe_raises_on_unsafe_value():
    with pytest.raises(UnsafeIdentifier):
        ensure_safe("tokio", "--malicious")


def test_unsafe_identifier_is_value_error():
    # So callers can catch ValueError if they prefer the broader type.
    assert issubclass(UnsafeIdentifier, ValueError)
