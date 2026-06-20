"""gh-release-pin scope: bump a structured pin when upstream ships a new release."""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from scripts.config import Config, CustomScope
from scripts.osv import OsvCache
from scripts.pr import apply_plan, capture_base_sha
from scripts.target_yaml_env_var import read_value, write_value
from scripts.types import Drift, Plan, Result

SCOPE = "gh-release-pin"


def _gh_latest(repo: str) -> str:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/latest", "--jq", ".tag_name"],
        capture_output=True, check=True, text=True,
    ).stdout.strip()
    return out


def detect(
    workdir: Path, custom: CustomScope,
    *,
    latest_resolver: Callable[[str], str] = _gh_latest,
) -> list[Drift]:
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
    latest = _strip_v(latest_resolver(upstream_repo))
    if _semver_eq(current, latest):
        return []
    if not _semver_gt(latest, current):
        return []
    return [Drift(
        scope=SCOPE, key=latest,
        summary=f"{custom.name}: bump to {latest}",
        fixed_versions=[latest], current=current,
        raw={"custom": custom, "target_file": str(target_file)},
    )]


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
        scope=SCOPE, key=drift.key,
        branch=f"sentinel/gh-release-pin/{custom.name}-{new_value}",
        title=f"{custom.name}: bump to {new_value}",
        body=body,
        files_changed=[str(target_file.relative_to(workdir))],
        commands=[], post_steps=(edit_target,),
    )


def run(
    workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool
) -> list[Result]:
    results: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    for custom in config.custom:
        if custom.kind != SCOPE:
            continue
        for drift in detect(workdir, custom):
            p = plan(workdir, drift, custom)
            results.append(apply_plan(
                p, dry_run=dry_run, workdir=workdir, base_sha=base_sha,
            ))
    return results


def _strip_v(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def _semver_eq(a: str, b: str) -> bool:
    return _parse(a) == _parse(b)


def _semver_gt(a: str, b: str) -> bool:
    return _parse(a) > _parse(b)


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v))
