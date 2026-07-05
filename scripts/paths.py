"""Containment for config-supplied filesystem paths.

`target_file` and `gomod_path` come from the repo's sentinel.toml. `config.py`
rejects absolute or `..` values at load; `resolve_within` is the defence at the
read/write site: it resolves the real path (following symlinks) and refuses
anything that lands outside the workspace, catching escapes a string check
cannot see.
"""

from __future__ import annotations

from pathlib import Path


class UnsafePath(ValueError):
    """Raised when a config-supplied path resolves outside the workspace."""


def resolve_within(base: Path, relative: str) -> Path:
    base_resolved = base.resolve()
    resolved = (base_resolved / relative).resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise UnsafePath(f"path escapes the workspace: {relative!r}")
    return resolved
