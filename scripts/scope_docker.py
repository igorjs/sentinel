"""docker scope: bump end-of-life official Python/Node base images in Dockerfiles."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from scripts.config import Config, effective_runtime_eol_lead_days, update_runtime_enabled
from scripts.models import Plan, Result
from scripts.pr import apply_plan, branch_name, capture_base_sha, open_issue_fallback
from scripts.runtime_eol import RuntimeEolError, eol_target, fetch_cycles

SCOPE = "docker"

# image (normalized) -> (endoflife product, cycle granularity, LTS-only targets)
_IMAGE_CFG: dict[str, tuple[str, int, bool]] = {
    "python": ("python", 2, False),
    "node": ("nodejs", 1, True),
}

_EXCLUDED_DIRS = {".git", "node_modules", "vendor", ".venv"}

_FROM_RE = re.compile(
    r"^(?P<prefix>\s*FROM\s+(?:--platform=\S+\s+)?)"
    r"(?P<image>[^\s:@]+)"
    r"(?::(?P<tag>[^\s@]+))?"
    r"(?P<digest>@\S+)?"
    r"(?P<rest>.*)$",
    re.IGNORECASE,
)

_TAG_RE = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")


@dataclass(frozen=True)
class FromRef:
    image: str | None  # normalized official image name ("python"/"node"), else None
    tag: str | None
    has_digest: bool


def _normalize_image(image: str) -> str:
    img = image.lower()
    for prefix in ("docker.io/library/", "docker.io/", "library/"):
        if img.startswith(prefix):
            return img[len(prefix) :]
    return img


def _is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def find_dockerfiles(workdir: Path) -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
        for f in files:
            if _is_dockerfile(f):
                out.append(Path(root) / f)
    return sorted(out)


def parse_from(line: str) -> FromRef | None:
    m = _FROM_RE.match(line)
    if not m:
        return None
    norm = _normalize_image(m["image"])
    image = norm if norm in _IMAGE_CFG else None
    return FromRef(image=image, tag=m["tag"], has_digest=bool(m["digest"]))


def parse_tag(tag: str) -> tuple[str, str] | None:
    m = _TAG_RE.match(tag)
    if not m:
        return None
    return m.group(1), m.group(2)


def bump_tag(
    numeric: str, suffix: str, target_cycle: str, target_latest: str, *, parts: int
) -> str:
    has_patch = len(numeric.split(".")) > parts
    return f"{target_latest if has_patch else target_cycle}{suffix}"


def bump_from_line(line: str, new_tag: str) -> str:
    m = _FROM_RE.match(line)
    if m is None:
        raise ValueError(f"not a FROM line: {line!r}")
    if m["digest"]:
        raise ValueError(f"refusing to rewrite a digest-pinned FROM line: {line!r}")
    return f"{m['prefix']}{m['image']}:{new_tag}{m['rest']}"


def scan(
    workdir: Path,
    *,
    lead_days: int,
    today: date,
    fetch: Callable[[str], list[dict]] = fetch_cycles,
) -> tuple[list[dict], list[dict]]:
    edits: list[dict] = []
    manual: list[dict] = []
    cache: dict[str, list[dict] | None] = {}

    def cycles_for(product: str) -> list[dict] | None:
        if product not in cache:
            try:
                cache[product] = fetch(product)
            except RuntimeEolError:
                cache[product] = None  # fail-closed
        return cache[product]

    for path in find_dockerfiles(workdir):
        rel = path.relative_to(workdir).as_posix()
        try:
            lines = path.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines):
            ref = parse_from(line)
            if ref is None or ref.image is None or ref.tag is None:
                continue
            product, parts, lts_only = _IMAGE_CFG[ref.image]
            parsed = parse_tag(ref.tag)
            if parsed is None:
                continue
            numeric, suffix = parsed
            cycles = cycles_for(product)
            if cycles is None:
                continue
            cycle = ".".join(numeric.split(".")[:parts])
            target = eol_target(cycles, cycle, today=today, lead_days=lead_days, lts_only=lts_only)
            if target is None:
                continue
            target_cycle, target_latest = target
            if ref.has_digest:
                manual.append({"file": rel, "image": ref.image, "tag": ref.tag})
                continue
            new_tag = bump_tag(numeric, suffix, target_cycle, target_latest, parts=parts)
            if new_tag == ref.tag:
                continue
            edits.append(
                {"file": rel, "lineno": i, "old": line, "new": bump_from_line(line, new_tag)}
            )
    return edits, manual


def _today() -> date:
    return date.today()


def _plan(workdir: Path, edits: list[dict]) -> Plan:
    files = sorted({e["file"] for e in edits})
    bullets = "\n".join(
        f"- `{e['file']}`: `{e['old'].strip()}` -> `{e['new'].strip()}`" for e in edits
    )
    title = "runtime(docker): raise end-of-life base image(s)"
    body = (
        "End-of-life (or near-EOL) Docker base image(s) raised to the oldest "
        "still-supported version.\n\n"
        f"{bullets}\n\n"
        "Source: [endoflife.date](https://endoflife.date). Independent of CVE severity.\n\n"
        "Opened automatically by [sentinel](https://github.com/igorjs/sentinel).\n"
    )

    def _apply(edits=edits) -> None:
        by_file: dict[str, list[dict]] = {}
        for e in edits:
            by_file.setdefault(e["file"], []).append(e)
        for rel, file_edits in by_file.items():
            path = workdir / rel
            with open(path, newline="") as f:  # newline="" => keep original endings
                lines = f.read().splitlines(keepends=True)
            for e in file_edits:
                i = e["lineno"]
                stripped = lines[i].rstrip("\r\n")
                ending = lines[i][len(stripped) :]
                lines[i] = e["new"] + ending
            with open(path, "w", newline="") as f:
                f.write("".join(lines))

    _apply.__name__ = "apply_docker_edits"
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
    # osv is unused (the dispatcher computes it for every builtin scope).
    if not update_runtime_enabled(config, SCOPE):
        return []
    lead = effective_runtime_eol_lead_days(config, SCOPE)
    edits, manual = scan(workdir, lead_days=lead, today=_today(), fetch=fetch_cycles)
    out: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    if edits:
        try:
            out.append(
                apply_plan(
                    _plan(workdir, edits),
                    dry_run=dry_run,
                    workdir=workdir,
                    base_sha=base_sha,
                    pr_labels=config.defaults.pr_labels,
                )
            )
        except (subprocess.CalledProcessError, OSError) as e:
            out.append(
                open_issue_fallback(
                    scope=SCOPE,
                    key="docker-eol",
                    title="sentinel: docker base-image bump failed",
                    body=f"Failed to apply Dockerfile base-image bump: {e}. Bump manually.",
                    dry_run=dry_run,
                    workdir=workdir,
                )
            )
    if manual:
        listing = "\n".join(f"- `{m['file']}`: `{m['image']}:{m['tag']}`" for m in manual)
        out.append(
            open_issue_fallback(
                scope=SCOPE,
                key="docker-eol-digest",
                title="sentinel: digest-pinned end-of-life base image(s)",
                body=(
                    "These digest-pinned base images are end-of-life but cannot be retagged "
                    f"automatically (the new tag's digest is unknown):\n\n{listing}\n\n"
                    "Update the tag and digest manually."
                ),
                dry_run=dry_run,
                workdir=workdir,
            )
        )
    return out
