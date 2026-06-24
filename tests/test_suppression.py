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
