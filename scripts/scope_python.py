"""python scope: bump PyPI deps when OSV reports a fixable advisory.
Detects lockfile to pick poetry/uv/pipenv. No lockfile → issue fallback."""

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
from scripts.severity import derive_severity, gate, severity_line
from scripts.suppression import osv_scanner_cleanup_step
from scripts.types import Drift, Plan, Result
from scripts.validate import UnsafeIdentifier, ensure_safe
from scripts.version import version_key

SCOPE = "python"

_PM_BY_LOCKFILE = [
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Pipfile.lock", "pipenv"),
]

_BUMP_CMD = {
    "poetry": lambda mod: ["poetry", "update", mod],
    "uv": lambda mod: ["uv", "lock", "--upgrade-package", mod],
    "pipenv": lambda mod: ["pipenv", "update", mod],
}


def detect_pkg_manager(workdir: Path) -> str | None:
    """Lockfile wins; pyproject.toml is the PEP 621 fallback."""
    for lockfile, pm in _PM_BY_LOCKFILE:
        if (workdir / lockfile).exists():
            return pm
    if (workdir / "pyproject.toml").exists():
        return "pyproject"
    return None


def _has_python_project(workdir: Path) -> bool:
    return (workdir / "pyproject.toml").exists() or (workdir / "requirements.txt").exists()


def detect(workdir: Path, osv: OsvCache) -> list[Drift]:
    if not _has_python_project(workdir):
        return []
    drifts: list[Drift] = []
    seen: set[tuple[str, str]] = set()
    for adv in osv.fixable_advisories("PyPI"):
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

    if pkg_manager == "pyproject":
        # Direct edit of pyproject.toml's [project.dependencies]
        pyproject_path = workdir / "pyproject.toml"

        def edit_pyproject() -> None:
            _edit_pyproject_pep621(pyproject_path, module, fix)

        edit_pyproject.__name__ = "edit_pyproject_dep"

        return Plan(
            scope=SCOPE,
            key=drift.key,
            branch=branch_name(SCOPE, f"{drift.key} {module}"),
            title=title,
            body=body,
            files_changed=["pyproject.toml"],
            commands=[],
            post_steps=(edit_pyproject, *((cleanup,) if cleanup else ())),
        )

    lockfiles = {"poetry": "poetry.lock", "uv": "uv.lock", "pipenv": "Pipfile.lock"}
    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=branch_name(SCOPE, f"{drift.key} {module}"),
        title=title,
        body=body,
        files_changed=["pyproject.toml", lockfiles[pkg_manager]],
        commands=[_BUMP_CMD[pkg_manager](module)],
        post_steps=(cleanup,) if cleanup else (),
    )


def _edit_pyproject_pep621(path: Path, module: str, new_version: str) -> None:
    """Edit a [project.dependencies] entry in-place. Preserves formatting via tomlkit.
    tomlkit is lazy-imported so non-python consumers don't pay for it."""
    import tomlkit

    doc = tomlkit.parse(path.read_text())
    deps = doc.get("project", {}).get("dependencies")
    if deps is None:
        raise KeyError(f"[project.dependencies] not found in {path}")
    target_norm = module.lower().replace("_", "-")
    for i, raw in enumerate(deps):
        m = re.match(r"^([A-Za-z0-9_.\-]+)(.*)$", str(raw).strip())
        if not m:
            continue
        name_norm = m.group(1).lower().replace("_", "-")
        if name_norm == target_norm:
            deps[i] = f"{module}=={new_version}"
            path.write_text(tomlkit.dumps(doc))
            return
    raise KeyError(f"{module} not found in [project.dependencies] of {path}")


def run(workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool) -> list[Result]:
    if not _has_python_project(workdir):
        return []
    pm = detect_pkg_manager(workdir)
    if pm is None:
        any_fixable = detect(workdir, osv)
        if not any_fixable:
            return []
        return [
            open_issue_fallback(
                scope=SCOPE,
                key="no-lockfile",
                title="sentinel: python no lockfile detected",
                body=(
                    "pyproject.toml or requirements.txt present but no lockfile "
                    "(poetry.lock / uv.lock / Pipfile.lock) found. Sentinel cannot "
                    "safely auto-bump pip deps without a lockfile.\n\n"
                    f"{len(any_fixable)} fixable advisor(ies) detected. "
                    "Adopt one of poetry/uv/pipenv to enable auto-bumping."
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
        except (subprocess.CalledProcessError, KeyError) as e:
            results.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key=drift.key,
                    title=f"sentinel: python bump blocked for {drift.key}",
                    body=f"Bump failed: {e}. Manual review needed.",
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )
    return results
