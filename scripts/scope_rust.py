"""rust scope: bump cargo deps when OSV reports a fixable advisory.
Self-cleans osv-scanner.toml and deny.toml ignore entries."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts.config import Config
from scripts.osv import OsvCache
from scripts.pr import apply_plan, capture_base_sha, open_issue_fallback
from scripts.types import Drift, Plan, Result

SCOPE = "rust"


def detect(workdir: Path, osv: OsvCache) -> list[Drift]:
    if not (workdir / "Cargo.lock").exists():
        return []
    lock = (workdir / "Cargo.lock").read_text()
    drifts: list[Drift] = []
    seen: set[str] = set()
    for adv in osv.fixable_advisories("crates.io"):
        adv_id = adv["id"]
        if adv_id in seen:
            continue
        seen.add(adv_id)
        for affected in adv.get("affected", []):
            pkg_name = affected.get("package", {}).get("name")
            if not pkg_name:
                continue
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
                key=_parse,
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
                    raw={"package": pkg_name, "advisory": adv},
                )
            )
            break
    return drifts


def plan(workdir: Path, drift: Drift) -> Plan:
    pkg = drift.raw["package"]
    fix = _minimum_acceptable_fix(drift.fixed_versions, drift.current)
    title = f"{drift.key}: bump {pkg} to {fix}"
    body = _pr_body(drift, fix)
    return Plan(
        scope=SCOPE,
        key=drift.key,
        branch=f"sentinel/rust/{drift.key.lower()}",
        title=title,
        body=body,
        files_changed=["Cargo.lock", "osv-scanner.toml", "deny.toml"],
        commands=[["cargo", "update", "-p", pkg, "--precise", fix]],
        post_steps=tuple(_self_cleaning_steps(workdir, drift.key)),
    )


def run(workdir: Path, config: Config, osv: OsvCache, *, dry_run: bool) -> list[Result]:
    results: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    for drift in detect(workdir, osv):
        p = plan(workdir, drift)
        try:
            results.append(
                apply_plan(
                    p,
                    dry_run=dry_run,
                    workdir=workdir,
                    base_sha=base_sha,
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
                        f"`{drift.raw['package']}` → "
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
        if _semver_ge(v, current):
            return v
    return fixed_versions[-1]


def _semver_ge(a: str, b: str) -> bool:
    return _parse(a) >= _parse(b)


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v))


def _pr_body(drift: Drift, fix: str) -> str:
    return (
        f"Closes [{drift.key}](https://osv.dev/{drift.key}).\n\n"
        f"**Advisory:** {drift.summary}\n\n"
        f"**Bump:** `{drift.raw['package']}` "
        f"{drift.current} → {fix}\n\n"
        f"Opened automatically by [sentinel]"
        f"(https://github.com/igorjs/sentinel).\n"
    )


def _self_cleaning_steps(workdir: Path, advisory_id: str) -> list:
    steps = []
    for filename, remover in [
        ("osv-scanner.toml", _remove_from_osv_scanner_toml),
        ("deny.toml", _remove_from_deny_toml),
    ]:
        path = workdir / filename
        if path.exists() and advisory_id in path.read_text():

            def make_step(p: Path, fn) -> callable:
                def step() -> None:
                    fn(p, advisory_id)

                step.__name__ = f"clean_{p.name}"
                return step

            steps.append(make_step(path, remover))
    return steps


def _remove_from_osv_scanner_toml(path: Path, advisory_id: str) -> None:
    text = path.read_text()
    pattern = re.compile(
        r"(?ms)^\[\[IgnoredVulns\]\]\s*\n"
        rf'.*?id\s*=\s*"{re.escape(advisory_id)}".*?(?=\n\[\[|\Z)'
    )
    new_text = pattern.sub("", text).rstrip() + "\n"
    path.write_text(new_text)


def _remove_from_deny_toml(path: Path, advisory_id: str) -> None:
    text = path.read_text()
    pattern = re.compile(rf'^\s*"{re.escape(advisory_id)}"\s*,?\s*$', re.MULTILINE)
    new_text = pattern.sub("", text)
    new_text = re.sub(r"\n\n\n+", "\n\n", new_text)
    path.write_text(new_text)
