"""ci scope: bump end-of-life python/node version-matrix entries in GitHub workflows."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

from scripts.config import Config, effective_runtime_eol_lead_days, update_runtime_enabled
from scripts.models import Plan, Result
from scripts.pr import apply_plan, branch_name, capture_base_sha, open_issue_fallback
from scripts.runtime_eol import (
    RuntimeEolError,
    bump_pin,
    eol_target,
    fetch_cycles,
    pin_cycle,
)

SCOPE = "ci"

# matrix key -> (endoflife product, cycle granularity, LTS-only targets)
_MATRIX_KEYS: dict[str, tuple[str, int, bool]] = {
    "python-version": ("python", 2, False),
    "node-version": ("nodejs", 1, True),
}

# runner-OS label prefix -> (endoflife product, cycle granularity, LTS-only targets)
_RUNNER_OS: dict[str, tuple[str, int, bool]] = {
    "ubuntu": ("ubuntu", 2, True),
    "macos": ("macos", 1, False),
    "windows": ("windows-server", 1, False),
}

_VERSION_SUFFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")


def _split_version_suffix(rest: str) -> tuple[str, str] | None:
    """Split a label remainder into (numeric version, verbatim suffix). None if no leading digit."""
    m = _VERSION_SUFFIX_RE.match(rest)
    if not m:
        return None
    return m.group(1), m.group(2)


def parse_runner_label(label: object) -> tuple[str, str, str, str] | None:
    """Parse a runner label '<os>-<version>[<suffix>]'. Returns (os, cycle, version, suffix) or None."""
    if not isinstance(label, str):
        return None
    os_name, sep, rest = label.partition("-")
    if not sep or os_name not in _RUNNER_OS:
        return None
    split = _split_version_suffix(rest)
    if split is None:
        return None
    version, suffix = split
    _, parts, _ = _RUNNER_OS[os_name]
    cycle = pin_cycle(version, parts=parts)
    if cycle is None:
        return None
    return os_name, cycle, version, suffix


def bump_runner_label(
    label: object,
    *,
    today: date,
    lead_days: int,
    cycles_for: Callable[[str], list[dict] | None],
) -> str | None:
    """Return the bumped runner label, or None if not bumpable / fail-closed."""
    parsed = parse_runner_label(label)
    if parsed is None:
        return None
    os_name, cycle, _version, suffix = parsed
    product, _parts, lts_only = _RUNNER_OS[os_name]
    cycles = cycles_for(product)
    if cycles is None:
        return None
    target = eol_target(cycles, cycle, today=today, lead_days=lead_days, lts_only=lts_only)
    if target is None:
        return None
    target_cycle, _target_latest = target
    new_label = f"{os_name}-{target_cycle}{suffix}"
    return new_label if new_label != label else None


def _reclothe(original: object, new_str: str) -> object | None:
    """Return new_str dressed in original's scalar style, or None if it can't be."""
    from ruamel.yaml.scalarstring import ScalarString

    if isinstance(original, ScalarString):
        return type(original)(new_str)  # preserve quote/style
    if isinstance(original, bool):
        return None
    if isinstance(original, int):
        try:
            return int(new_str)
        except ValueError:
            return None
    if isinstance(original, str):
        return new_str
    return None  # float / other -> leave untouched


def bump_matrix_list(seq, cfg, *, today, lead_days, cycles) -> bool:
    _, parts, lts_only = cfg
    changed = False
    for i in range(len(seq)):
        s = str(seq[i])
        cycle = pin_cycle(s, parts=parts)
        if cycle is None:
            continue
        target = eol_target(cycles, cycle, today=today, lead_days=lead_days, lts_only=lts_only)
        if target is None:
            continue
        target_cycle, target_latest = target
        new_str = bump_pin(s, target_cycle, target_latest, parts=parts)
        if new_str == s:
            continue
        new_val = _reclothe(seq[i], new_str)
        if new_val is None:
            continue
        seq[i] = new_val
        changed = True
    if changed:
        seen: set[str] = set()
        i = 0
        while i < len(seq):
            key = str(seq[i])
            if key in seen:
                del seq[i]
            else:
                seen.add(key)
                i += 1
    return changed


def find_workflows(workdir: Path) -> list[Path]:
    wf_dir = workdir / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    return sorted(p for p in wf_dir.iterdir() if p.is_file() and p.suffix in (".yml", ".yaml"))


def scan(
    workdir: Path,
    *,
    lead_days: int,
    today: date,
    fetch: Callable[[str], list[dict]] = fetch_cycles,
) -> list[dict]:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    edits: list[dict] = []
    cache: dict[str, list[dict] | None] = {}

    def cycles_for(product: str) -> list[dict] | None:
        if product not in cache:
            try:
                cache[product] = fetch(product)
            except RuntimeEolError:
                cache[product] = None
        return cache[product]

    for path in find_workflows(workdir):
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        try:
            doc = yaml.load(path)
        except (YAMLError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        changed_keys: list[str] = []
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            matrix = (job.get("strategy") or {}).get("matrix")
            if not isinstance(matrix, dict):
                continue
            for key, cfg in _MATRIX_KEYS.items():
                seq = matrix.get(key)
                if not isinstance(seq, list):
                    continue
                cycles = cycles_for(cfg[0])
                if cycles is None:
                    continue
                if bump_matrix_list(seq, cfg, today=today, lead_days=lead_days, cycles=cycles):
                    changed_keys.append(key)
        if changed_keys:
            edits.append(
                {
                    "file": path.relative_to(workdir).as_posix(),
                    "path": path,
                    "doc": doc,
                    "yaml": yaml,
                    "keys": sorted(set(changed_keys)),
                }
            )
    return edits


def _today() -> date:
    return date.today()


def _plan(edits: list[dict]) -> Plan:
    files = sorted(e["file"] for e in edits)
    bullets = "\n".join(f"- `{e['file']}`: {', '.join(e['keys'])}" for e in edits)
    title = "runtime(ci): drop end-of-life version-matrix entries"
    body = (
        "End-of-life Python/Node version-matrix entries replaced with the oldest "
        "still-supported version.\n\n"
        f"{bullets}\n\n"
        "Source: [endoflife.date](https://endoflife.date). Independent of CVE severity.\n\n"
        "Opened automatically by [sentinel](https://github.com/igorjs/sentinel).\n"
    )

    def _apply(edits=edits) -> None:
        for e in edits:
            e["yaml"].dump(e["doc"], e["path"])

    _apply.__name__ = "apply_ci_edits"
    return Plan(
        scope=SCOPE,
        key="runtime-eol",
        branch=branch_name(SCOPE, "runtime-eol"),
        title=title,
        body=body,
        files_changed=files,
        commands=[],
        post_steps=(_apply,),
    )


def run(workdir: Path, config: Config, osv: object, *, dry_run: bool) -> list[Result]:
    # osv unused (the dispatcher computes it for every builtin scope).
    if not update_runtime_enabled(config, SCOPE):
        return []
    from ruamel.yaml.error import YAMLError

    lead = effective_runtime_eol_lead_days(config, SCOPE)
    edits = scan(workdir, lead_days=lead, today=_today(), fetch=fetch_cycles)
    if not edits:
        return []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    try:
        return [
            apply_plan(
                _plan(edits),
                dry_run=dry_run,
                workdir=workdir,
                base_sha=base_sha,
                pr_labels=config.defaults.pr_labels,
            )
        ]
    except (subprocess.CalledProcessError, OSError, YAMLError) as e:
        return [
            open_issue_fallback(
                scope=SCOPE,
                key="ci-eol",
                title="sentinel: CI version-matrix bump failed",
                body=f"Failed to apply the workflow matrix bump: {e}. Bump manually.",
                dry_run=dry_run,
                workdir=workdir,
            )
        ]
