"""One OSV advisory can affect multiple packages. Each affected package must get
its own drift and its own branch, or bumps silently clobber each other on a
shared branch."""

from pathlib import Path

from scripts import scope_go, scope_javascript, scope_python, scope_rust
from scripts.models import Drift
from scripts.osv import OsvCache


def _drift(scope: str, field: str, name: str, fixed: list[str]) -> Drift:
    return Drift(
        scope=scope,
        key="OSV-2024-MULTI",
        summary="affects several packages",
        fixed_versions=fixed,
        current="1.0.0",
        raw={field: name, "advisory": {}},
    )


def test_rust_two_crates_one_advisory_get_distinct_branches(tmp_path: Path):
    b_a = scope_rust.plan(tmp_path, _drift("rust", "package", "crate-a", ["1.1.0"])).branch
    b_b = scope_rust.plan(tmp_path, _drift("rust", "package", "crate-b", ["1.1.0"])).branch
    assert b_a != b_b
    assert b_a.startswith("sentinel/rust/") and b_b.startswith("sentinel/rust/")
    assert "crate-a" in b_a and "crate-b" in b_b


def test_go_two_modules_one_advisory_get_distinct_branches(tmp_path: Path):
    gomod = tmp_path / "go.mod"
    b_a = scope_go.plan_module(
        tmp_path, _drift("go", "module", "example.com/a", ["1.1.0"]), gomod
    ).branch
    b_b = scope_go.plan_module(
        tmp_path, _drift("go", "module", "example.com/b", ["1.1.0"]), gomod
    ).branch
    assert b_a != b_b


def test_javascript_two_packages_one_advisory_get_distinct_branches(tmp_path: Path):
    b_a = scope_javascript.plan(
        tmp_path, _drift("javascript", "module", "pkg-a", ["1.1.0"]), "npm"
    ).branch
    b_b = scope_javascript.plan(
        tmp_path, _drift("javascript", "module", "pkg-b", ["1.1.0"]), "npm"
    ).branch
    assert b_a != b_b


def test_python_two_packages_one_advisory_get_distinct_branches(tmp_path: Path):
    b_a = scope_python.plan(
        tmp_path, _drift("python", "module", "pkg-a", ["1.1.0"]), "poetry"
    ).branch
    b_b = scope_python.plan(
        tmp_path, _drift("python", "module", "pkg-b", ["1.1.0"]), "poetry"
    ).branch
    assert b_a != b_b


def test_rust_detect_emits_a_drift_per_affected_crate(tmp_path: Path):
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "crate-a"\nversion = "1.0.0"\n\n'
        '[[package]]\nname = "crate-b"\nversion = "2.0.0"\n'
    )
    osv = OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "crates.io", "name": "crate-a"},
                            "vulnerabilities": [
                                {
                                    "id": "RUSTSEC-2024-MULTI",
                                    "summary": "s",
                                    "affected": [
                                        {
                                            "package": {"name": "crate-a"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "1.1.0"},
                                                    ]
                                                }
                                            ],
                                        },
                                        {
                                            "package": {"name": "crate-b"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "2.2.0"},
                                                    ]
                                                }
                                            ],
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )
    drifts = scope_rust.detect(tmp_path, osv)
    bumped = {d.raw["package"] for d in drifts}
    assert bumped == {"crate-a", "crate-b"}
