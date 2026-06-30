"""Version-freshness engine: select outdated deps and open grouped PRs.

The per-ecosystem adapter (injected) does the package-manager work; this module
owns policy (level, include/exclude), grouping, PR/issue shaping, and fail-closed.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch

from scripts.config import (
    Config,
    effective_freshness_group,
    effective_freshness_level,
    freshness_filters,
    update_freshness_enabled,
)
from scripts.models import Plan, Result
from scripts.pr import apply_plan, branch_name, capture_base_sha, open_issue_fallback
from scripts.version import version_key


class FreshnessError(RuntimeError):
    """A package manager was unavailable, or returned unusable data."""


@dataclass(frozen=True)
class Outdated:
    name: str
    current: str
    wanted: str  # latest within the declared range
    latest: str  # absolute latest stable


@dataclass(frozen=True)
class Selection:
    name: str
    current: str
    target: str
    is_major: bool


def _vgt(a: str, b: str) -> bool:
    """True when version a sorts strictly above version b."""
    return version_key(a) > version_key(b)


def select(
    outdated: list[Outdated],
    *,
    level: str,
    include: list[str],
    exclude: list[str],
) -> list[Selection]:
    """Pick a bump target per dep, honouring level and include/exclude globs."""
    out: list[Selection] = []
    for o in outdated:
        if include and not any(fnmatch(o.name, pat) for pat in include):
            continue
        if any(fnmatch(o.name, pat) for pat in exclude):
            continue
        target, is_major = o.wanted, False
        if level == "major" and _vgt(o.latest, o.wanted):
            target, is_major = o.latest, True
        if target == o.current:
            continue
        out.append(Selection(name=o.name, current=o.current, target=target, is_major=is_major))
    return sorted(out, key=lambda s: s.name)


def _dependabot_note(workdir) -> str:
    if (workdir / ".github" / "dependabot.yml").exists():
        return (
            "Note: this repo also configures Dependabot. Scope sentinel's freshness "
            "with `freshness_include` / `freshness_exclude` to avoid overlapping PRs."
        )
    return ""


def _body(selections: list[Selection], note: str) -> str:
    lines = "\n".join(
        f"- `{s.name}`: {s.current} -> {s.target}" + (" (major)" if s.is_major else "")
        for s in selections
    )
    parts = [lines]
    if note:
        parts.append(note)
    parts.append("Opened automatically by [sentinel](https://github.com/igorjs/sentinel).")
    return "\n\n".join(parts) + "\n"


def _plan(
    scope: str, selections: list[Selection], adapter, workdir, note: str, *, per_dep: bool
) -> Plan:
    if per_dep:
        key = f"freshness-{selections[0].name}"
        title = f"freshness({scope}): bump {selections[0].name} to {selections[0].target}"
    else:
        key = "freshness"
        noun = "dependency" if len(selections) == 1 else "dependencies"
        title = f"freshness({scope}): update {len(selections)} {noun}"

    def _apply(workdir=workdir, selections=selections):
        adapter.apply(workdir, selections)

    _apply.__name__ = "apply_freshness"
    return Plan(
        scope=scope,
        key=key,
        branch=branch_name(scope, key),
        title=title,
        body=_body(selections, note),
        files_changed=list(adapter.FILES_CHANGED),
        commands=[],
        post_steps=(_apply,),
    )


def _issue(scope: str, detail: str, *, dry_run: bool, workdir) -> Result:
    return open_issue_fallback(
        scope=scope,
        key=f"{scope}-freshness",
        title=f"sentinel: {scope} freshness update failed",
        body=f"Freshness update could not be applied: {detail}. Bump manually.",
        dry_run=dry_run,
        workdir=workdir,
    )


def run(workdir, config: Config, *, dry_run: bool, adapter) -> list[Result]:
    scope = adapter.SCOPE
    if not update_freshness_enabled(config, scope):
        return []
    try:
        outdated = adapter.list_outdated(workdir)
    except FreshnessError as e:
        return [_issue(scope, str(e), dry_run=dry_run, workdir=workdir)]
    include, exclude = freshness_filters(config, scope)
    selections = select(
        outdated,
        level=effective_freshness_level(config, scope),
        include=include,
        exclude=exclude,
    )
    if not selections:
        return []
    note = _dependabot_note(workdir)
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    per_dep = effective_freshness_group(config, scope) == "dependency"
    if per_dep:
        groups = [[s] for s in selections]
    else:
        groups = [selections]
    results: list[Result] = []
    for group in groups:
        plan = _plan(scope, group, adapter, workdir, note, per_dep=per_dep)
        try:
            results.append(
                apply_plan(
                    plan,
                    dry_run=dry_run,
                    workdir=workdir,
                    base_sha=base_sha,
                    pr_labels=config.defaults.pr_labels,
                )
            )
        except (subprocess.CalledProcessError, OSError, FreshnessError) as e:
            results.append(_issue(scope, str(e), dry_run=dry_run, workdir=workdir))
    return results
