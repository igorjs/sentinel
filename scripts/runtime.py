"""Runtime declaration registry: read/write the version declarations sentinel
bumps when a runtime reaches end of life."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
