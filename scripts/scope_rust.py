"""rust scope: bump cargo deps when OSV reports a fixable advisory.
Self-cleans osv-scanner.toml and deny.toml ignore entries."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts.config import Config, effective_min_severity
from scripts.models import Drift, Plan, Result
from scripts.osv import OsvCache
from scripts.pr import (
    apply_plan,
    branch_name,
    open_issue_fallback,
    open_unsafe_identifier_issue,
)
from scripts.severity import derive_severity, gate, severity_line
from scripts.suppression import osv_scanner_cleanup_step
from scripts.validate import UnsafeIdentifier, ensure_safe
from scripts.version import version_key

SCOPE = "rust"


def detect(workdir: Path, osv: OsvCache) -> list[Drift]:
    if not (workdir / "Cargo.lock").exists():
        return []
    lock = (workdir / "Cargo.lock").read_text()
    drifts: list[Drift] = []
    seen: set[tuple[str, str]] = set()
    for adv in osv.fixable_advisories("crates.io"):
        adv_id = adv["id"]
        for affected in adv.get("affected", []):
            pkg_name = affected.get("package", {}).get("name")
            if not pkg_name:
                continue
            if (adv_id, pkg_name) in seen:
                continue
            seen.add((adv_id, pkg_name))
            current = _current_version(lock, pkg_name)
            if current is None:
                continue
            fixed = sorted(
                {
                    e["fixed"]
                    for r in affected.get("ranges", [])
                    for e in r.get("events", [])
                    if "fixed" in e
                },
                key=version_key,
            )
            if not fixed:
                continue
            drifts.append(
                Drift(
                    scope=SCOPE,
                    key=adv_id,
                    summary=adv.get("summary", adv_id),
                    fixed_versions=fixed,
                    current=current,
                    severity=derive_severity(adv, score=osv.max_severity(adv_id)),
                    raw={"package": pkg_name, "advisory": adv},
                )
            )
    return drifts


def plan(workdir: Path, drift: Drift, *, clean_suppressions: bool = True) -> Plan:
    pkg = drift.raw["package"]
    fix = _minimum_acceptable_fix(drift.fixed_versions, drift.current)
    ensure_safe(pkg, fix)
    title = f"{drift.key}: bump {pkg} to {fix}"
    body = _pr_body(drift, fix)
    # The osv-scanner.toml / deny.toml suppressions are keyed by advisory, not
    # crate. When one advisory affects several crates, each gets its own PR;
    # only one of them should strip the shared suppression so the siblings don't
    # carry redundant, competing ignore-file edits (clean_suppressions=False).
    post_steps = tuple(_self_cleaning_steps(workdir, drift.key)) if clean_suppressions else ()
    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=branch_name(SCOPE, f"{drift.key} {pkg}"),
        title=title,
        body=body,
        files_changed=["Cargo.lock", "osv-scanner.toml", "deny.toml"],
        commands=[["cargo", "update", "-p", pkg, "--precise", fix]],
        post_steps=post_steps,
    )


def run(workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool) -> list[Result]:
    results: list[Result] = []
    threshold = effective_min_severity(config, SCOPE)
    drifts, skipped = gate(detect(workdir, osv), threshold)
    if skipped:
        print(f"[{SCOPE}] skipped {skipped} advisor(ies) below min_severity={threshold}")
    cleaned: set[str] = set()  # advisories whose suppression cleanup is already claimed
    for drift in drifts:
        clean = drift.key not in cleaned
        try:
            p = plan(workdir, drift, clean_suppressions=clean)
        except UnsafeIdentifier as e:
            results.append(
                open_unsafe_identifier_issue(
                    scope=SCOPE, key=drift.key, error=e, dry_run=dry_run, workdir=workdir
                )
            )
            continue
        if clean:
            cleaned.add(drift.key)
        try:
            results.append(
                apply_plan(
                    p,
                    dry_run=dry_run,
                    workdir=workdir,
                    pr_labels=config.defaults.pr_labels,
                )
            )
        except subprocess.CalledProcessError as e:
            results.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key=drift.key,
                    title=f"sentinel: rust bump blocked for {drift.key}",
                    body=(
                        f"`cargo update --precise` failed for "
                        f"`{drift.raw['package']}` -> "
                        f"`{drift.fixed_versions[0]}`. Exit code {e.returncode}.\n\n"
                        "A parent dep range likely pins the affected crate. "
                        "Manual bump required."
                    ),
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )
    return results


def _current_version(lock_text: str, pkg: str) -> str | None:
    pattern = re.compile(
        rf'\[\[package\]\]\s*\nname\s*=\s*"{re.escape(pkg)}"\s*\nversion\s*=\s*"([^"]+)"',
        re.MULTILINE,
    )
    m = pattern.search(lock_text)
    return m.group(1) if m else None


def _minimum_acceptable_fix(fixed_versions: list[str], current: str) -> str:
    for v in fixed_versions:
        if version_key(v) >= version_key(current):
            return v
    return fixed_versions[-1]


def _pr_body(drift: Drift, fix: str) -> str:
    return (
        f"Closes [{drift.key}](https://osv.dev/{drift.key}).\n\n"
        f"**Advisory:** {drift.summary}\n\n"
        f"{severity_line(drift.severity)}\n\n"
        f"**Bump:** `{drift.raw['package']}` "
        f"{drift.current} -> {fix}\n\n"
        f"Opened automatically by [sentinel]"
        f"(https://github.com/igorjs/sentinel).\n"
    )


def _self_cleaning_steps(workdir: Path, advisory_id: str) -> list:
    # osv-scanner.toml cleanup is shared across scopes; deny.toml is cargo-deny
    # specific and stays here.
    steps = []
    osv_step = osv_scanner_cleanup_step(workdir, advisory_id)
    if osv_step:
        steps.append(osv_step)
    deny_path = workdir / "deny.toml"
    if deny_path.exists() and advisory_id in deny_path.read_text():

        def step() -> None:
            _remove_from_deny_toml(deny_path, advisory_id)

        step.__name__ = "clean_deny.toml"
        steps.append(step)
    return steps


def _remove_from_deny_toml(path: Path, advisory_id: str) -> None:
    text = path.read_text()
    pattern = re.compile(rf'^\s*"{re.escape(advisory_id)}"\s*,?\s*$', re.MULTILINE)
    new_text = pattern.sub("", text)
    new_text = re.sub(r"\n\n\n+", "\n\n", new_text)
    path.write_text(new_text)
