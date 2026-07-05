from pathlib import Path

import pytest

from scripts.paths import UnsafePath, resolve_within


def test_resolve_within_returns_contained_path(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    got = resolve_within(tmp_path, "sub/go.mod")
    assert got == (tmp_path / "sub" / "go.mod").resolve()


def test_resolve_within_allows_missing_file(tmp_path: Path):
    # The target need not exist yet (it may be created by a bump).
    assert (
        resolve_within(tmp_path, "not-created-yet.mod")
        == (tmp_path / "not-created-yet.mod").resolve()
    )


def test_resolve_within_rejects_parent_traversal(tmp_path: Path):
    base = tmp_path / "work"
    base.mkdir()
    with pytest.raises(UnsafePath):
        resolve_within(base, "../secret.txt")


def test_resolve_within_rejects_symlink_escape(tmp_path: Path):
    base = tmp_path / "work"
    base.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (base / "link.mod").symlink_to(outside)
    with pytest.raises(UnsafePath):
        resolve_within(base, "link.mod")
