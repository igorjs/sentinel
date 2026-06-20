"""TOML config loader for .github/sentinel.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ALLOWED_TOP = {"scopes", "custom", "defaults"}
_ALLOWED_SCOPE_OVERRIDE = {"enabled", "gomod_path", "update_runtime"}
_REQUIRED_CUSTOM = {"name", "kind"}
_ALLOWED_DEFAULTS = {"pr_labels"}


class ConfigError(ValueError):
    pass


@dataclass
class ScopeOverride:
    enabled: bool = True
    gomod_path: str | None = None
    update_runtime: bool = True


@dataclass
class CustomScope:
    name: str
    kind: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Defaults:
    pr_labels: list[str] = field(
        default_factory=lambda: ["dependencies", "automated"]
    )


@dataclass
class Config:
    scopes: dict[str, ScopeOverride] = field(default_factory=dict)
    custom: list[CustomScope] = field(default_factory=list)
    defaults: Defaults = field(default_factory=Defaults)


def load_config(path: Path | None) -> Config:
    if path is None or not path.exists():
        return Config()
    with path.open("rb") as f:
        data = tomllib.load(f)
    _reject_unknown(data, _ALLOWED_TOP, where="top-level")

    cfg = Config()
    for name, spec in (data.get("scopes") or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"scopes.{name} must be a table")
        _reject_unknown(spec, _ALLOWED_SCOPE_OVERRIDE, where=f"scopes.{name}")
        cfg.scopes[name] = ScopeOverride(
            enabled=bool(spec.get("enabled", True)),
            gomod_path=spec.get("gomod_path"),
            update_runtime=bool(spec.get("update_runtime", True)),
        )

    for i, raw in enumerate(data.get("custom") or []):
        if not isinstance(raw, dict):
            raise ConfigError(f"custom[{i}] must be a table")
        missing = _REQUIRED_CUSTOM - raw.keys()
        if missing:
            raise ConfigError(
                f"custom[{i}]: missing required key(s): {sorted(missing)}"
            )
        cfg.custom.append(CustomScope(
            name=str(raw["name"]),
            kind=str(raw["kind"]),
            extra={k: v for k, v in raw.items() if k not in _REQUIRED_CUSTOM},
        ))

    defaults = data.get("defaults") or {}
    if defaults:
        _reject_unknown(defaults, _ALLOWED_DEFAULTS, where="defaults")
        labels = defaults.get("pr_labels")
        if labels is not None:
            if not (isinstance(labels, list) and all(isinstance(x, str) for x in labels)):
                raise ConfigError("defaults.pr_labels must be a list of strings")
            cfg.defaults.pr_labels = list(labels)

    return cfg


def _reject_unknown(data: dict, allowed: set[str], *, where: str) -> None:
    extras = set(data.keys()) - allowed
    if extras:
        raise ConfigError(
            f"{where}: unknown key(s): {sorted(extras)} (allowed: {sorted(allowed)})"
        )
