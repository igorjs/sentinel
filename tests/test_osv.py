from pathlib import Path

import pytest

from scripts import osv as osv_mod
from scripts.osv import OsvCache, _recovered_packages, from_fixture, parse_ignored_ids


def test_empty_fixture_no_advisories(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_empty.json")
    assert cache.advisories("crates.io") == []
    assert cache.fixable_advisories("crates.io") == []


def test_cargo_fixture_finds_advisory(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    advs = cache.advisories("crates.io")
    assert len(advs) == 1
    assert advs[0]["id"] == "RUSTSEC-2024-9999"


def test_cargo_fixture_advisory_is_fixable(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    fixable = cache.fixable_advisories("crates.io")
    assert len(fixable) == 1


def test_filter_by_package(fixtures_dir: Path):
    cache = from_fixture(fixtures_dir / "osv_cargo_fixable.json")
    assert len(cache.advisories("crates.io", package="tokio")) == 1
    assert cache.advisories("crates.io", package="other") == []


def test_scan_missing_binary_raises_clear_error(tmp_path: Path, monkeypatch):
    def _raise(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "osv-scanner")

    monkeypatch.setattr(osv_mod.subprocess, "run", _raise)
    with pytest.raises(RuntimeError, match="osv-scanner not found"):
        OsvCache.scan(tmp_path)


def test_max_severity_from_groups_by_id_and_alias():
    cache = OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "groups": [
                                {"ids": ["GHSA-1"], "aliases": ["CVE-1"], "max_severity": "8.6"}
                            ]
                        }
                    ]
                }
            ]
        }
    )
    assert cache.max_severity("GHSA-1") == 8.6
    assert cache.max_severity("CVE-1") == 8.6  # matched via aliases
    assert cache.max_severity("NOPE") is None


def test_max_severity_missing_or_unparseable():
    cache = OsvCache({"results": [{"packages": [{"groups": [{"ids": ["G"]}]}]}]})
    assert cache.max_severity("G") is None  # no max_severity field


def test_parse_ignored_ids():
    text = '[[IgnoredVulns]]\nid = "RUSTSEC-1"\n[[IgnoredVulns]]\nid = "GHSA-2"\n'
    assert parse_ignored_ids(text) == {"RUSTSEC-1", "GHSA-2"}


def test_parse_ignored_ids_empty_and_malformed():
    assert parse_ignored_ids("") == set()
    assert parse_ignored_ids("not [valid toml") == set()


def test_recovered_packages_filters_to_suppressed_and_keeps_groups():
    audit = {
        "results": [
            {
                "packages": [
                    {
                        "package": {"name": "foo"},
                        "groups": [{"ids": ["X"], "max_severity": "7.5"}],
                        "vulnerabilities": [{"id": "X"}, {"id": "Y"}],
                    },
                    {
                        "package": {"name": "bar"},
                        "vulnerabilities": [{"id": "Z"}],
                    },  # none suppressed
                ]
            }
        ]
    }
    rec = _recovered_packages(audit, {"X"})
    assert len(rec) == 1  # bar dropped (no suppressed vuln)
    assert [v["id"] for v in rec[0]["vulnerabilities"]] == ["X"]  # Y dropped
    assert rec[0]["groups"] == [{"ids": ["X"], "max_severity": "7.5"}]  # groups preserved


def test_scan_with_recovery_merges_suppressed_fixable(tmp_path, monkeypatch):
    (tmp_path / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "RUSTSEC-SUP"\n')
    normal = {"results": []}  # suppressed advisory is excluded from the normal scan
    audit = {
        "results": [
            {
                "packages": [
                    {
                        "package": {"ecosystem": "crates.io", "name": "foo"},
                        "groups": [{"ids": ["RUSTSEC-SUP"], "max_severity": "8.0"}],
                        "vulnerabilities": [
                            {
                                "id": "RUSTSEC-SUP",
                                "affected": [
                                    {
                                        "package": {"name": "foo"},
                                        "ranges": [
                                            {"events": [{"introduced": "0"}, {"fixed": "2.0.0"}]}
                                        ],
                                    }
                                ],
                            },
                            {  # non-suppressed: must NOT be recovered
                                "id": "RUSTSEC-OTHER",
                                "affected": [
                                    {
                                        "package": {"name": "foo"},
                                        "ranges": [{"events": [{"fixed": "1.0"}]}],
                                    }
                                ],
                            },
                        ],
                    }
                ]
            }
        ]
    }

    def fake_raw(workdir, *, bypass_ignores=False):
        return audit if bypass_ignores else normal

    monkeypatch.setattr(osv_mod, "_raw_scan", fake_raw)
    cache = OsvCache.scan_with_recovery(tmp_path)
    ids = [a["id"] for a in cache.fixable_advisories("crates.io")]
    assert ids == ["RUSTSEC-SUP"]  # only the suppressed-and-present one recovered
    assert cache.max_severity("RUSTSEC-SUP") == 8.0  # groups survived the merge


def test_scan_with_recovery_noop_without_toml(tmp_path, monkeypatch):
    calls = []

    def fake_raw(workdir, *, bypass_ignores=False):
        calls.append(bypass_ignores)
        return {"results": []}

    monkeypatch.setattr(osv_mod, "_raw_scan", fake_raw)
    OsvCache.scan_with_recovery(tmp_path)  # no osv-scanner.toml present
    assert calls == [False]  # only the normal scan; no bypass audit
