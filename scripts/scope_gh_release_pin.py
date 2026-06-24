"""gh-release-pin scope: bump a structured pin when upstream ships a new release."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from scripts.config import Config, CustomScope
from scripts.models import Drift, Plan, Result
from scripts.osv import OsvCache
from scripts.pr import apply_plan, capture_base_sha, open_issue_fallback
from scripts.target_yaml_env_var import read_value, write_value
from scripts.version import version_key

SCOPE = "gh-release-pin"


def _gh_latest(repo: str) -> str:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/latest", "--jq", ".tag_name"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    return out


def detect(
    workdir: Path,
    custom: CustomScope,
    *,
    latest_resolver: Callable[[str], str] | None = None,
) -> list[Drift]:
    # Resolve at call time (not as a default arg) so run() and tests can swap it.
    resolve = latest_resolver or _gh_latest
    upstream_repo = custom.extra["upstream_repo"]
    target_file = workdir / custom.extra["target_file"]
    if not target_file.exists():
        return []
    target_kind = custom.extra["target_kind"]
    if target_kind != "yaml-env-var":
        raise ValueError(f"unknown target_kind: {target_kind}")
    env_var = custom.extra["env_var"]
    env_path = custom.extra.get("env_path", "env")
    current = read_value(target_file, env_var, env_path=env_path)
    if current is None:
        return []
    latest = _strip_v(resolve(upstream_repo))
    if version_key(current) == version_key(latest):
        return []
    if not version_key(latest) > version_key(current):
        return []
    return [
        Drift(
            scope=SCOPE,
            key=latest,
            summary=f"{custom.name}: bump to {latest}",
            fixed_versions=[latest],
            current=current,
            raw={"custom": custom, "target_file": str(target_file)},
        )
    ]


def plan(workdir: Path, drift: Drift, custom: CustomScope) -> Plan:
    new_value = drift.fixed_versions[0]
    target_file = Path(drift.raw["target_file"])
    env_var = custom.extra["env_var"]
    env_path = custom.extra.get("env_path", "env")
    upstream_repo = custom.extra["upstream_repo"]

    def edit_target() -> None:
        write_value(target_file, env_var, new_value, env_path=env_path)

    edit_target.__name__ = f"edit_{target_file.name}"

    body = (
        f"Bumps `{custom.name}` pin from `{drift.current}` to `{new_value}`.\n\n"
        f"Upstream release: "
        f"https://github.com/{upstream_repo}/releases/tag/v{new_value}\n\n"
        f"Opened automatically by [sentinel]"
        f"(https://github.com/igorjs/sentinel).\n"
    )
    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=f"sentinel/gh-release-pin/{custom.name}-{new_value}",
        title=f"{custom.name}: bump to {new_value}",
        body=body,
        files_changed=[str(target_file.relative_to(workdir))],
        commands=[],
        post_steps=(edit_target,),
    )


def run(workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool) -> list[Result]:
    results: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    for custom in config.custom:
        if custom.kind != SCOPE:
            continue
        try:
            drifts = detect(workdir, custom)
        except subprocess.CalledProcessError as e:
            results.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key=custom.name,
                    title=f"sentinel: {custom.name} upstream lookup failed",
                    body=(
                        f"Could not resolve the latest release for "
                        f"`{custom.extra.get('upstream_repo', '?')}` (exit {e.returncode}). "
                        "Manual review needed."
                    ),
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )
            continue
        for drift in drifts:
            try:
                p = plan(workdir, drift, custom)
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
                        title=f"sentinel: {custom.name} pin bump blocked",
                        body=(
                            f"Bumping `{custom.name}` to `{drift.fixed_versions[0]}` failed: "
                            f"{e}. Manual review needed."
                        ),
                        dry_run=dry_run,
                        workdir=workdir,
                    )
                )
    return results


def _strip_v(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag
