"""Self-cleaning of osv-scanner.toml suppressions when a bump closes an advisory.

osv-scanner.toml ignore entries apply across ecosystems, so this is shared by
every scope. deny.toml is cargo-deny-specific and stays in the rust scope.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path


def osv_scanner_cleanup_step(workdir: Path, advisory_id: str) -> Callable[[], None] | None:
    """A post-step that removes ``advisory_id`` from ``workdir/osv-scanner.toml``.

    Returns None when the file is absent or doesn't reference the advisory, so a
    scope only attaches the step when there's actually a suppression to clear.
    """
    path = workdir / "osv-scanner.toml"
    if not path.exists() or advisory_id not in path.read_text():
        return None

    def step() -> None:
        _remove_from_osv_scanner_toml(path, advisory_id)

    step.__name__ = "clean_osv-scanner.toml"
    return step


def _remove_from_osv_scanner_toml(path: Path, advisory_id: str) -> None:
    text = path.read_text()
    pattern = re.compile(
        r"(?ms)^\[\[IgnoredVulns\]\]\s*\n"
        rf'.*?id\s*=\s*"{re.escape(advisory_id)}".*?(?=\n\[\[|\Z)'
    )
    new_text = pattern.sub("", text).rstrip() + "\n"
    path.write_text(new_text)
