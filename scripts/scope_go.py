"""go scope: bumps module deps + optionally the `go <version>` runtime directive."""

from __future__ import annotations

import re
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
from scripts.severity import SEVERITY_ORDER, derive_severity, gate, meets_threshold, severity_line
from scripts.suppression import osv_scanner_cleanup_step
from scripts.types import Drift, Plan, Result
from scripts.validate import UnsafeIdentifier, ensure_safe
from scripts.version import version_key

SCOPE = "go"


def detect_module_drifts(workdir: Path, osv: OsvCache, gomod_path: Path) -> list[Drift]:
    if not gomod_path.exists():
        return []
    drifts: list[Drift] = []
    seen: set[tuple[str, str]] = set()
    for adv in osv.fixable_advisories("Go"):
        for affected in adv.get("affected", []):
            module = affected.get("package", {}).get("name")
            if not module or module == "stdlib":
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


def detect_runtime_drift(workdir: Path, osv: OsvCache, gomod_path: Path) -> Drift | None:
    if not gomod_path.exists():
        return None
    current = _current_directive(gomod_path.read_text())
    if current is None:
        return None
    fixable: list[str] = []
    advisory_ids: list[str] = []
    severities: list[str] = []
    for adv in osv.fixable_advisories("Go"):
        is_stdlib = any(
            a.get("package", {}).get("name") == "stdlib" for a in adv.get("affected", [])
        )
        if not is_stdlib:
            continue
        candidates = sorted(
            {
                e["fixed"]
                for a in adv.get("affected", [])
                if a.get("package", {}).get("name") == "stdlib"
                for r in a.get("ranges", [])
                for e in r.get("events", [])
                if "fixed" in e
            },
            key=version_key,
        )
        best = next((v for v in candidates if version_key(v) >= version_key(current)), None)
        if best is None:
            continue
        fixable.append(best)
        advisory_ids.append(adv["id"])
        severities.append(derive_severity(adv, score=osv.max_severity(adv["id"])))
    if not fixable:
        return None
    target = max(fixable, key=version_key)
    known = [s for s in severities if s in SEVERITY_ORDER]
    runtime_severity = max(known, key=SEVERITY_ORDER.index) if known else "unknown"
    return Drift(
        scope=SCOPE,
        key="runtime-" + "-".join(sorted(advisory_ids))[:50],
        summary=f"Clear {len(advisory_ids)} Go stdlib advisor(ies)",
        fixed_versions=[target],
        current=current,
        severity=runtime_severity,
        raw={"advisory_ids": advisory_ids, "target": target},
    )


def plan_module(
    workdir: Path, drift: Drift, gomod_path: Path, *, clean_suppressions: bool = True
) -> Plan:
    module = drift.raw["module"]
    fix = drift.fixed_versions[0]
    ensure_safe(module, fix)
    cleanup = osv_scanner_cleanup_step(workdir, drift.key) if clean_suppressions else None
    title = f"{drift.key}: bump {module} to {fix}"
    body = (
        f"Closes [{drift.key}](https://osv.dev/{drift.key}).\n\n"
        f"**Advisory:** {drift.summary}\n\n"
        f"{severity_line(drift.severity)}\n\n"
        f"**Bump:** `{module}` → {fix}\n\n"
        f"Opened automatically by [sentinel]"
        f"(https://github.com/igorjs/sentinel).\n"
    )
    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=branch_name(SCOPE, f"{drift.key} {module}"),
        title=title,
        body=body,
        files_changed=[
            str(gomod_path.relative_to(workdir)),
            str((gomod_path.parent / "go.sum").relative_to(workdir)),
        ],
        commands=[
            ["go", "get", f"{module}@{fix}"],
            ["go", "mod", "tidy"],
        ],
        post_steps=(cleanup,) if cleanup else (),
    )


def plan_runtime(workdir: Path, drift: Drift, gomod_path: Path) -> Plan:
    target = drift.raw["target"]
    advisories = drift.raw["advisory_ids"]
    items = "\n".join(f"- [{a}](https://osv.dev/{a})" for a in advisories)
    body = (
        f"Bumps the Go runtime pin from `{drift.current}` to `{target}`, "
        f"clearing:\n\n{items}\n\n"
        f"This is a Go language-version directive bump (not a module dep). "
        f"Review the Go release notes before merging.\n\n"
        f"Opened automatically by [sentinel]"
        f"(https://github.com/igorjs/sentinel).\n"
    )

    def edit_gomod() -> None:
        text = gomod_path.read_text()
        new_text = re.sub(
            r"^go\s+\S+\s*$",
            f"go {target}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        gomod_path.write_text(new_text)

    edit_gomod.__name__ = "edit_gomod_directive"

    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=f"sentinel/go/runtime-{target}",
        title=f"go: bump runtime to {target}",
        body=body,
        files_changed=[str(gomod_path.relative_to(workdir))],
        commands=[],
        post_steps=(edit_gomod,),
    )


def run(workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool) -> list[Result]:
    override = config.scopes.get(SCOPE)
    gomod_path = workdir / (override.gomod_path if override and override.gomod_path else "go.mod")
    update_runtime = override.update_runtime if override else True

    results: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    threshold = effective_min_severity(config, SCOPE)

    module_drifts, skipped = gate(detect_module_drifts(workdir, osv, gomod_path), threshold)
    if skipped:
        print(f"[{SCOPE}] skipped {skipped} advisor(ies) below min_severity={threshold}")
    cleaned: set[str] = set()  # advisories whose suppression cleanup is already claimed
    for drift in module_drifts:
        clean = drift.key not in cleaned
        try:
            p = plan_module(workdir, drift, gomod_path, clean_suppressions=clean)
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
                    title=f"sentinel: go bump blocked for {drift.key}",
                    body=f"`go get` failed (exit {e.returncode}). Manual review needed.",
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )

    runtime_drift = detect_runtime_drift(workdir, osv, gomod_path)
    if runtime_drift and not meets_threshold(runtime_drift.severity, threshold):
        print(f"[{SCOPE}] skipped runtime bump below min_severity={threshold}")
        runtime_drift = None
    if runtime_drift:
        if update_runtime:
            p = plan_runtime(workdir, runtime_drift, gomod_path)
            results.append(
                apply_plan(
                    p,
                    dry_run=dry_run,
                    workdir=workdir,
                    base_sha=base_sha,
                    pr_labels=config.defaults.pr_labels,
                )
            )
        else:
            advisories = runtime_drift.raw["advisory_ids"]
            target = runtime_drift.raw["target"]
            results.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key=runtime_drift.key,
                    title=f"sentinel: go runtime bump required ({target})",
                    body=(
                        f"Sentinel detected Go stdlib advisories that can only be "
                        f"cleared by bumping the Go runtime from "
                        f"`{runtime_drift.current}` to `{target}`.\n\n"
                        f"`update_runtime = false` is set for this scope, so "
                        f"sentinel will not edit the `go` directive automatically.\n\n"
                        f"Affected advisories:\n"
                        + "\n".join(f"- [{a}](https://osv.dev/{a})" for a in advisories)
                    ),
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )
    return results


def _current_directive(text: str) -> str | None:
    m = re.search(r"^go\s+(\S+)\s*$", text, re.MULTILINE)
    return m.group(1) if m else None
