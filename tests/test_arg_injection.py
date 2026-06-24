"""Each scope must refuse to build a command from an advisory whose package name
or fixed version is an unsafe argv token (argument injection)."""

from pathlib import Path

import pytest

from scripts import scope_go, scope_javascript, scope_python, scope_rust
from scripts.config import load_config
from scripts.models import Drift
from scripts.osv import OsvCache
from scripts.validate import UnsafeIdentifier


def _drift(scope: str, name_field: str, name: str, fixed: list[str]) -> Drift:
    return Drift(
        scope=scope,
        key="OSV-2024-EVIL",
        summary="evil",
        fixed_versions=fixed,
        current="1.0.0",
        raw={name_field: name},
    )


def test_rust_plan_rejects_flaglike_package(tmp_path: Path):
    drift = _drift("rust", "package", "--config=evil", ["1.2.3"])
    with pytest.raises(UnsafeIdentifier):
        scope_rust.plan(tmp_path, drift)


def test_rust_plan_rejects_flaglike_version(tmp_path: Path):
    drift = _drift("rust", "package", "serde", ["-rf"])
    with pytest.raises(UnsafeIdentifier):
        scope_rust.plan(tmp_path, drift)


def test_go_plan_module_rejects_flaglike_module(tmp_path: Path):
    drift = _drift("go", "module", "--evil", ["v1.2.3"])
    with pytest.raises(UnsafeIdentifier):
        scope_go.plan_module(tmp_path, drift, tmp_path / "go.mod")


def test_javascript_plan_rejects_flaglike_module(tmp_path: Path):
    drift = _drift("javascript", "module", "--evil", ["1.2.3"])
    with pytest.raises(UnsafeIdentifier):
        scope_javascript.plan(tmp_path, drift, "npm")


def test_python_plan_rejects_flaglike_module(tmp_path: Path):
    drift = _drift("python", "module", "--evil", ["1.2.3"])
    with pytest.raises(UnsafeIdentifier):
        scope_python.plan(tmp_path, drift, "poetry")


def test_rust_run_routes_unsafe_advisory_to_issue(tmp_path: Path):
    """End-to-end (dry-run): a malicious advisory is skipped and reported, never bumped."""
    (tmp_path / "Cargo.lock").write_text('[[package]]\nname = "--evil"\nversion = "1.0.0"\n')
    osv = OsvCache(
        {
            "results": [
                {
                    "packages": [
                        {
                            "package": {"ecosystem": "crates.io", "name": "--evil"},
                            "vulnerabilities": [
                                {
                                    "id": "RUSTSEC-2024-EVIL",
                                    "summary": "evil",
                                    "affected": [
                                        {
                                            "package": {"name": "--evil"},
                                            "ranges": [
                                                {
                                                    "events": [
                                                        {"introduced": "0"},
                                                        {"fixed": "1.2.3"},
                                                    ]
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )
    results = scope_rust.run(tmp_path, load_config(None), osv, dry_run=True)
    assert len(results) == 1
    assert "unsafe advisory data" in results[0].summary
