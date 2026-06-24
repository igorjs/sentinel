"""javascript scope: bump npm deps when OSV reports a fixable advisory.
Detects lockfile to pick npm/pnpm/yarn. No lockfile → issue fallback."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.config import Config, effective_min_severity
from scripts.osv import OsvCache
from scripts.pr import (
    apply_plan,
    branch_name,
    capture_base_sha,
    open_issue_fallback,
    open_unsafe_identifier_issue,
)
from scripts.severity import derive_severity, gate, severity_line
from scripts.suppression import osv_scanner_cleanup_step
from scripts.types import Drift, Plan, Result
from scripts.validate import UnsafeIdentifier, ensure_safe
from scripts.version import version_key

SCOPE = "javascript"

_PM_BY_LOCKFILE = [
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
]

_BUMP_CMD = {
    "npm": lambda mod, fix: ["npm", "install", f"{mod}@{fix}"],
    "pnpm": lambda mod, fix: ["pnpm", "update", f"{mod}@{fix}"],
    "yarn": lambda mod, fix: ["yarn", "upgrade", f"{mod}@{fix}"],
}


def detect_pkg_manager(workdir: Path) -> str | None:
    for lockfile, pm in _PM_BY_LOCKFILE:
        if (workdir / lockfile).exists():
            return pm
    return None


def detect(workdir: Path, osv: OsvCache) -> list[Drift]:
    if not (workdir / "package.json").exists():
        return []
    drifts: list[Drift] = []
    seen: set[tuple[str, str]] = set()
    for adv in osv.fixable_advisories("npm"):
        for affected in adv.get("affected", []):
            module = affected.get("package", {}).get("name")
            if not module:
                continue
            key = (adv["id"], module)
            if key in seen:
                continue
            seen.add(key)
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
                    key=adv["id"],
                    summary=adv.get("summary", adv["id"]),
                    fixed_versions=fixed,
                    current="",
                    severity=derive_severity(adv, score=osv.max_severity(adv["id"])),
                    raw={"module": module, "advisory": adv},
                )
            )
    return drifts


def plan(workdir: Path, drift: Drift, pkg_manager: str, *, clean_suppressions: bool = True) -> Plan:
    module = drift.raw["module"]
    fix = drift.fixed_versions[0]
    ensure_safe(module, fix)
    cleanup = osv_scanner_cleanup_step(workdir, drift.key) if clean_suppressions else None
    title = f"{drift.key}: bump {module} to {fix}"
    body = (
        f"Closes [{drift.key}](https://osv.dev/{drift.key}).\n\n"
        f"**Advisory:** {drift.summary}\n\n"
        f"{severity_line(drift.severity)}\n\n"
        f"**Bump:** `{module}` → {fix} (via {pkg_manager})\n\n"
        f"Opened automatically by [sentinel]"
        f"(https://github.com/igorjs/sentinel).\n"
    )
    lockfiles = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock"}
    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=branch_name(SCOPE, f"{drift.key} {module}"),
        title=title,
        body=body,
        files_changed=["package.json", lockfiles[pkg_manager]],
        commands=[_BUMP_CMD[pkg_manager](module, fix)],
        post_steps=(cleanup,) if cleanup else (),
    )


def run(workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool) -> list[Result]:
    if not (workdir / "package.json").exists():
        return []
    pm = detect_pkg_manager(workdir)
    if pm is None:
        # No lockfile → can't safely auto-bump
        any_fixable = detect(workdir, osv)
        if not any_fixable:
            return []
        return [
            open_issue_fallback(
                scope=SCOPE,
                key="no-lockfile",
                title="sentinel: javascript no lockfile detected",
                body=(
                    "package.json present but no lockfile (package-lock.json / "
                    "pnpm-lock.yaml / yarn.lock) found. Sentinel cannot safely "
                    "auto-bump npm deps without a lockfile.\n\n"
                    f"{len(any_fixable)} fixable advisor(ies) detected. "
                    "Commit a lockfile to enable auto-bumping."
                ),
                dry_run=dry_run,
                workdir=workdir,
            )
        ]
    results: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    threshold = effective_min_severity(config, SCOPE)
    detected, skipped = gate(detect(workdir, osv), threshold)
    if skipped:
        print(f"[{SCOPE}] skipped {skipped} advisor(ies) below min_severity={threshold}")
    cleaned: set[str] = set()  # advisories whose suppression cleanup is already claimed
    for drift in detected:
        clean = drift.key not in cleaned
        try:
            p = plan(workdir, drift, pm, clean_suppressions=clean)
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
                    base_sha=base_sha,
                    pr_labels=config.defaults.pr_labels,
                )
            )
        except subprocess.CalledProcessError as e:
            results.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key=drift.key,
                    title=f"sentinel: javascript bump blocked for {drift.key}",
                    body=f"`{pm}` failed (exit {e.returncode}). Manual review needed.",
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )
    return results
