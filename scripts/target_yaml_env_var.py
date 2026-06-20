"""yaml-env-var target_kind. Lazy-loads ruamel.yaml inside functions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def read_value(file: Path, env_var: str, env_path: str = "env") -> str | None:
    block = _load_block(file, env_path)
    if block is None:
        return None
    value = block.get(env_var)
    return str(value) if value is not None else None


def write_value(file: Path, env_var: str, new_value: str, env_path: str = "env") -> None:
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(file.read_text())
    block = _walk_path(data, env_path)
    if block is None or env_var not in block:
        raise KeyError(f"env var {env_var} not found at {env_path} in {file}")
    block[env_var] = new_value
    with file.open("w") as f:
        yaml.dump(data, f)


def _load_block(file: Path, env_path: str) -> dict[str, Any] | None:
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(file.read_text())
    return _walk_path(data, env_path)


def _walk_path(data: Any, env_path: str) -> Any:
    current: Any = data
    for part in _split_path(env_path):
        if current is None:
            return None
        if isinstance(part, int):
            try:
                current = current[part]
            except (IndexError, TypeError):
                return None
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
    return current


def _split_path(env_path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for raw in env_path.split("."):
        m = re.match(r"^([^[]+)(\[(\d+)\])?$", raw)
        if not m:
            raise ValueError(f"unparseable env_path segment: {raw}")
        tokens.append(m.group(1))
        if m.group(3) is not None:
            tokens.append(int(m.group(3)))
    return tokens
