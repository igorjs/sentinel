from pathlib import Path

from scripts.suppression import osv_scanner_cleanup_step


def test_cleanup_step_none_when_file_absent(tmp_path: Path):
    assert osv_scanner_cleanup_step(tmp_path, "RUSTSEC-1") is None


def test_cleanup_step_none_when_id_not_present(tmp_path: Path):
    (tmp_path / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "OTHER"\n')
    assert osv_scanner_cleanup_step(tmp_path, "RUSTSEC-1") is None


def test_cleanup_step_removes_matching_entry(tmp_path: Path):
    (tmp_path / "osv-scanner.toml").write_text(
        '[[IgnoredVulns]]\nid = "GHSA-1"\nreason = "no fix"\n\n'
        '[[IgnoredVulns]]\nid = "GHSA-2"\nreason = "keep"\n'
    )
    step = osv_scanner_cleanup_step(tmp_path, "GHSA-1")
    assert step is not None
    assert step.__name__ == "clean_osv-scanner.toml"
    step()
    text = (tmp_path / "osv-scanner.toml").read_text()
    assert "GHSA-1" not in text
    assert "GHSA-2" in text  # unrelated suppression preserved


def test_cleanup_removes_only_target_not_surrounding_blocks(tmp_path: Path):
    # Target is neither first nor last: the over-deletion bug wiped the blocks
    # BEFORE the target. Only the target block may be removed.
    (tmp_path / "osv-scanner.toml").write_text(
        '[[IgnoredVulns]]\nid = "KEEP-1"\nreason = "a"\n\n'
        '[[IgnoredVulns]]\nid = "KEEP-2"\nreason = "b"\n\n'
        '[[IgnoredVulns]]\nid = "TARGET"\nreason = "c"\n\n'
        '[[IgnoredVulns]]\nid = "KEEP-4"\nreason = "d"\n'
    )
    step = osv_scanner_cleanup_step(tmp_path, "TARGET")
    assert step is not None
    step()
    text = (tmp_path / "osv-scanner.toml").read_text()
    assert 'id = "TARGET"' not in text
    for keep in ("KEEP-1", "KEEP-2", "KEEP-4"):
        assert keep in text, f"{keep} was wrongly deleted"


def test_cleanup_leaves_valid_toml_with_only_target_gone(tmp_path: Path):
    import tomllib

    (tmp_path / "osv-scanner.toml").write_text(
        '[[IgnoredVulns]]\nid = "KEEP-1"\n\n'
        '[[IgnoredVulns]]\nid = "TARGET"\n\n'
        '[[IgnoredVulns]]\nid = "KEEP-3"\n'
    )
    osv_scanner_cleanup_step(tmp_path, "TARGET")()
    data = tomllib.loads((tmp_path / "osv-scanner.toml").read_text())
    ids = {e["id"] for e in data.get("IgnoredVulns", [])}
    assert ids == {"KEEP-1", "KEEP-3"}
