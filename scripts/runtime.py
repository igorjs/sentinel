"""Runtime declaration registry: read/write the version declarations sentinel
bumps when a runtime reaches end of life."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from scripts.config import Config, effective_runtime_eol_lead_days, update_runtime_enabled
from scripts.models import Drift, Plan, Result
from scripts.pr import apply_plan, branch_name, capture_base_sha, open_issue_fallback
from scripts.runtime_eol import (
    RuntimeEolError,
    bump_floor,
    bump_pin,
    eol_target,
    fetch_cycles,
    floor_lower_cycle,
    pin_cycle,
)

RUNTIME_KEY = "runtime-eol"

_ENGINES_NODE_RE = re.compile(r'("engines"\s*:\s*\{[^}]*?"node"\s*:\s*")([^"]*)(")', re.DOTALL)


def read_requires_python(workdir: Path) -> str | None:
    path = workdir / "pyproject.toml"
    if not path.exists():
        return None
    import tomllib

    data = tomllib.loads(path.read_text())
    value = data.get("project", {}).get("requires-python")
    return value if isinstance(value, str) else None


def write_requires_python(workdir: Path, new_spec: str) -> None:
    import tomlkit

    path = workdir / "pyproject.toml"
    doc = tomlkit.parse(path.read_text())
    project = doc.get("project")
    if project is None or "requires-python" not in project:
        raise KeyError("requires-python not found in [project]")
    project["requires-python"] = new_spec
    path.write_text(tomlkit.dumps(doc))


def read_engines_node(workdir: Path) -> str | None:
    path = workdir / "package.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    node = data.get("engines", {}).get("node")
    return node if isinstance(node, str) else None


def write_engines_node(workdir: Path, new_spec: str) -> None:
    path = workdir / "package.json"
    text = path.read_text()
    new_text, n = _ENGINES_NODE_RE.subn(lambda m: f"{m.group(1)}{new_spec}{m.group(3)}", text)
    if n != 1:
        raise KeyError("could not locate engines.node for a minimal-diff edit")
    path.write_text(new_text)


def read_pin(name: str) -> Callable[[Path], str | None]:
    def _read(workdir: Path) -> str | None:
        path = workdir / name
        return path.read_text().strip() if path.exists() else None

    return _read


def write_pin(name: str) -> Callable[[Path, str], None]:
    def _write(workdir: Path, new_value: str) -> None:
        path = workdir / name
        had_newline = path.exists() and path.read_text().endswith("\n")
        path.write_text(new_value + ("\n" if had_newline else ""))

    return _write


@dataclass(frozen=True)
class Decl:
    label: str  # human label, e.g. "requires-python"
    file: str  # file changed, e.g. "pyproject.toml"
    kind: str  # "floor" or "pin"
    read: Callable[[Path], str | None]
    write: Callable[[Path, str], None]


@dataclass(frozen=True)
class ProductCfg:
    product: str  # endoflife.date api name: "python" | "nodejs"
    parts: int  # cycle granularity: 2 for python, 1 for node
    lts_only: bool
    decls: tuple[Decl, ...]


PRODUCTS: dict[str, ProductCfg] = {
    "python": ProductCfg(
        product="python",
        parts=2,
        lts_only=False,
        decls=(
            Decl(
                "requires-python",
                "pyproject.toml",
                "floor",
                read_requires_python,
                write_requires_python,
            ),
            Decl(
                ".python-version",
                ".python-version",
                "pin",
                read_pin(".python-version"),
                write_pin(".python-version"),
            ),
        ),
    ),
    "javascript": ProductCfg(
        product="nodejs",
        parts=1,
        lts_only=True,
        decls=(
            Decl("engines.node", "package.json", "floor", read_engines_node, write_engines_node),
            Decl(".nvmrc", ".nvmrc", "pin", read_pin(".nvmrc"), write_pin(".nvmrc")),
            Decl(
                ".node-version",
                ".node-version",
                "pin",
                read_pin(".node-version"),
                write_pin(".node-version"),
            ),
        ),
    ),
}


def detect_runtime_drift(
    workdir: Path,
    scope: str,
    *,
    lead_days: int,
    today: date,
    fetch: Callable[[str], list[dict]] = fetch_cycles,
) -> Drift | None:
    cfg = PRODUCTS[scope]
    present = [(d, d.read(workdir)) for d in cfg.decls]
    present = [(d, raw) for d, raw in present if raw is not None]
    if not present:
        return None
    try:
        cycles = fetch(cfg.product)
    except RuntimeEolError:
        return None  # fail-closed

    edits: list[dict] = []
    unparseable: list[str] = []
    for decl, raw in present:
        current = (
            floor_lower_cycle(raw, parts=cfg.parts)
            if decl.kind == "floor"
            else pin_cycle(raw, parts=cfg.parts)
        )
        if current is None:
            unparseable.append(decl.label)
            continue
        target = eol_target(
            cycles, current, today=today, lead_days=lead_days, lts_only=cfg.lts_only
        )
        if target is None:
            continue
        target_cycle, target_latest = target
        new = (
            bump_floor(raw, target_cycle)
            if decl.kind == "floor"
            else bump_pin(raw, target_cycle, target_latest, parts=cfg.parts)
        )
        if new == raw:
            continue
        edits.append(
            {
                "label": decl.label,
                "file": decl.file,
                "current": raw,
                "new": new,
                "write": decl.write,
            }
        )

    if not edits and not unparseable:
        return None
    summary = (
        "raise end-of-life runtime: "
        + ", ".join(f"{e['label']} {e['current']}→{e['new']}" for e in edits)
        if edits
        else "end-of-life runtime detected (manual review)"
    )
    return Drift(
        scope=scope,
        key=RUNTIME_KEY,
        summary=summary,
        fixed_versions=[e["new"] for e in edits],
        current=", ".join(f"{e['label']}={e['current']}" for e in edits),
        severity="none",
        raw={"product": cfg.product, "edits": edits, "unparseable": unparseable},
    )


def runtime_plan(workdir: Path, drift: Drift, scope: str) -> Plan:
    edits = drift.raw["edits"]
    files = [e["file"] for e in edits]
    bullets = "\n".join(f"- `{e['file']}`: `{e['current']}` → `{e['new']}`" for e in edits)
    title = f"runtime({scope}): raise end-of-life runtime declaration(s)"
    body = (
        "End-of-life (or near-EOL) runtime declaration(s) raised to the oldest "
        "still-supported version.\n\n"
        f"{bullets}\n\n"
        "Source: [endoflife.date](https://endoflife.date). Independent of CVE severity.\n\n"
        "Opened automatically by [sentinel](https://github.com/igorjs/sentinel).\n"
    )

    def _apply(edits=edits) -> None:
        for e in edits:
            e["write"](workdir, e["new"])

    _apply.__name__ = "apply_runtime_edits"
    return Plan(
        scope=scope,
        key=RUNTIME_KEY,
        branch=branch_name(scope, RUNTIME_KEY),
        title=title,
        body=body,
        files_changed=files,
        commands=[],
        post_steps=(_apply,),
    )


def _today() -> date:
    return date.today()


def runtime_results(workdir: Path, config: Config, scope: str, *, dry_run: bool) -> list[Result]:
    """Shared entry point for the runtime-EOL path. Both scopes call this.

    Gates on update_runtime (opt-in); on a drift, opens the bump PR and/or an
    issue for any declaration that is EOL but unparseable. Fail-closed: a
    network error inside detect_runtime_drift yields no drift (no result).
    """
    if not update_runtime_enabled(config, scope):
        return []
    lead = effective_runtime_eol_lead_days(config, scope)
    drift = detect_runtime_drift(workdir, scope, lead_days=lead, today=_today(), fetch=fetch_cycles)
    if drift is None:
        return []
    out: list[Result] = []
    base_sha = capture_base_sha(workdir) if not dry_run else ""
    if drift.raw["edits"]:
        p = runtime_plan(workdir, drift, scope)
        out.append(
            apply_plan(
                p,
                dry_run=dry_run,
                workdir=workdir,
                base_sha=base_sha,
                pr_labels=config.defaults.pr_labels,
            )
        )
    if drift.raw["unparseable"]:
        out.append(
            open_issue_fallback(
                scope=scope,
                key="runtime-eol-unparseable",
                title="sentinel: unparseable runtime declaration(s)",
                body=(
                    "These runtime declarations look end-of-life but sentinel could not "
                    f"parse them safely: {', '.join(drift.raw['unparseable'])}. Bump manually."
                ),
                dry_run=dry_run,
                workdir=workdir,
            )
        )
    return out
