"""Validation of advisory-sourced identifiers before they reach subprocess argv.

OSV advisory data is third-party, untrusted input. Package names and fixed
versions from it flow into package-manager command lines (``cargo``, ``go``,
``npm``, ``poetry`` ...). Sentinel always builds those as argv lists, never via a
shell, so classic shell injection is not possible. But a value that begins with
``-`` would be parsed as a *flag* by the package manager (argument injection),
and whitespace/metacharacters have no place in a real package name or version.

``is_safe_arg`` is an allowlist: a token must start with an alphanumeric or ``@``
(npm scopes) and otherwise contain only characters that appear in legitimate
package names and versions across the supported ecosystems.
"""

from __future__ import annotations

import re

# Start with alphanumeric or '@' (npm scope); thereafter only characters seen in
# real package names / module paths / versions across crates.io, Go, npm, PyPI.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@~+-]*$")


class UnsafeIdentifier(ValueError):
    """Raised when an advisory-sourced identifier is unsafe to pass to a tool."""


def is_safe_arg(value: str) -> bool:
    """True if ``value`` is safe to place in a subprocess argv token.

    Rejects empty strings, leading-dash tokens (argument injection), and anything
    containing whitespace, shell metacharacters, or control characters.
    """
    return bool(_SAFE_TOKEN.fullmatch(value))


def ensure_safe(*values: str) -> None:
    """Raise :class:`UnsafeIdentifier` if any value fails :func:`is_safe_arg`."""
    for value in values:
        if not is_safe_arg(value):
            raise UnsafeIdentifier(f"unsafe identifier rejected: {value!r}")
