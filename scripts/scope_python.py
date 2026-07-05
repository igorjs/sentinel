"""python scope: bump PyPI deps when OSV reports a fixable advisory.
Detects lockfile to pick poetry/uv/pipenv. No lockfile -> issue fallback."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from scripts import runtime
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
from scripts.version import pypi_key

SCOPE = "python"


class DowngradeBlocked(ValueError):
    """Every fix would pin the dependency below the project's existing floor."""


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
                key=pypi_key,
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


def _current_spec(pyproject_path: Path, module: str) -> SpecifierSet | None:
    """The version specifier for ``module`` in [project.dependencies], or None."""
    try:
        doc = tomllib.loads(pyproject_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    target = module.lower().replace("_", "-")
    for raw in doc.get("project", {}).get("dependencies") or []:
        try:
            req = Requirement(str(raw))
        except InvalidRequirement:
            continue
        if req.name.lower().replace("_", "-") == target:
            return req.specifier if len(req.specifier) else None
    return None


def _lower_bound(spec: SpecifierSet) -> str | None:
    """The highest lower-edge version across the specifier's >=, ==, ~=, > clauses."""
    lowers: list[Version] = []
    for s in spec:
        if s.operator in (">=", "==", "~=", ">"):
            try:
                lowers.append(Version(s.version))
            except InvalidVersion:
                continue
    return str(max(lowers)) if lowers else None


def _select_pyproject_fix(pyproject_path: Path, module: str, fixed_versions: list[str]) -> str:
    """Pick the fix to pin without downgrading below the project's constraint.

    ``fixed_versions`` is sorted ascending. Prefer the smallest fix that
    satisfies the current constraint; if none does (the fix must cross it), the
    smallest fix at or above the constraint's lower bound; else the smallest fix.
    """
    spec = _current_spec(pyproject_path, module)
    if spec is None:
        return fixed_versions[0]
    satisfying = [v for v in fixed_versions if spec.contains(v, prereleases=True)]
    if satisfying:
        return satisfying[0]
    lower = _lower_bound(spec)
    if lower is not None:
        above = [v for v in fixed_versions if pypi_key(v) >= pypi_key(lower)]
        if above:
            return above[0]
        raise DowngradeBlocked(
            f"no fix for {module} is at or above the project's floor {lower!r}; "
            "auto-bumping would downgrade below the required version"
        )
    return fixed_versions[0]


def plan(workdir: Path, drift: Drift, pkg_manager: str, *, clean_suppressions: bool = True) -> Plan:
    module = drift.raw["module"]
    if pkg_manager == "pyproject":
        fix = _select_pyproject_fix(workdir / "pyproject.toml", module, drift.fixed_versions)
    else:
        fix = drift.fixed_versions[0]
    ensure_safe(module, fix)
    cleanup = osv_scanner_cleanup_step(workdir, drift.key) if clean_suppressions else None
    title = f"{drift.key}: bump {module} to {fix}"
    body = (
        f"Closes [{drift.key}](https://osv.dev/{drift.key}).\n\n"
        f"**Advisory:** {drift.summary}\n\n"
        f"{severity_line(drift.severity)}\n\n"
        f"**Bump:** `{module}` -> {fix} (via {pkg_manager})\n\n"
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
    results: list[Result] = runtime.runtime_results(workdir, config, SCOPE, dry_run=dry_run)
    pm = detect_pkg_manager(workdir)
    if pm is None:
        any_fixable = detect(workdir, osv)
        if not any_fixable:
            return results
        return [
            *results,
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
            ),
        ]
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
        except DowngradeBlocked as e:
            results.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key=drift.key,
                    title=f"sentinel: python bump for {drift.key} would downgrade",
                    body=(
                        f"{e}. The advisory's fixes are all below the version this "
                        "project already requires, so sentinel will not auto-bump. "
                        "Manual review needed."
                    ),
                    dry_run=dry_run,
                    workdir=workdir,
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
