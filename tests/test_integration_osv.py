"""End-to-end check against the real osv-scanner binary.

Every other test feeds synthetic OsvCache fixtures, so a change in osv-scanner's
`--format json` schema (as happened in v2.x) passes the unit suite while breaking
production. This test runs the actual scanner and asserts sentinel still parses
its output and detects a known, long-fixed advisory.

Skipped when osv-scanner isn't on PATH (most local dev). CI installs the pinned
version and runs it, so the pinned binary's schema is exercised on every push.
Needs network (osv.dev).
"""

import shutil

import pytest

from scripts.osv import OsvCache
from scripts.scope_python import detect

pytestmark = pytest.mark.skipif(
    shutil.which("osv-scanner") is None, reason="osv-scanner not installed"
)


def test_real_scan_parses_and_detects_known_advisory(tmp_path):
    # jinja2 2.10 carries long-standing, already-fixed PyPI advisories on osv.dev.
    (tmp_path / "requirements.txt").write_text("jinja2==2.10\n")

    cache = OsvCache.scan(tmp_path)  # real osv-scanner, real network
    drifts = detect(tmp_path, cache)

    assert drifts, "real osv-scanner output produced no drifts, parsing likely broke"
    jinja = [d for d in drifts if d.raw["module"].lower() == "jinja2"]
    assert jinja, f"expected a jinja2 drift, got modules {[d.raw['module'] for d in drifts]}"
    assert jinja[0].fixed_versions, "advisory parsed without a fixed version"
