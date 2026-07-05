"""TOML config loader for .github/sentinel.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.severity import SEVERITY_ORDER

_ALLOWED_TOP = {"scopes", "custom", "defaults"}
_ALLOWED_SCOPE_OVERRIDE = {
    "enabled",
    "gomod_path",
    "update_runtime",
    "min_severity",
    "runtime_eol_lead_days",
    "update_freshness",
    "freshness_level",
    "freshness_group",
    "freshness_include",
    "freshness_exclude",
}
_REQUIRED_CUSTOM = {"name", "kind"}
_ALLOWED_DEFAULTS = {
    "pr_labels",
    "min_severity",
    "runtime_eol_lead_days",
    "freshness_level",
    "freshness_group",
}

_FRESHNESS_LEVELS = {"range", "major"}
_FRESHNESS_GROUPS = {"scope", "dependency"}

# Per-kind required keys (beyond name/kind) for custom scopes. Validated at load
# time so a misconfigured scope fails loud here instead of with a bare KeyError
# mid-run.
_REQUIRED_CUSTOM_EXTRA = {
    "gh-release-pin": {"upstream_repo", "target_file", "target_kind", "env_var"},
}


class ConfigError(ValueError):
    pass


def _validate_lead_days(value: Any, *, where: str) -> int:
    # tomllib gives bool for `true`, float for `1.5`, int for `7`.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"{where}.runtime_eol_lead_days must be a non-negative integer, got {value!r}"
        )
    if value < 0:
        raise ConfigError(f"{where}.runtime_eol_lead_days must be >= 0, got {value!r}")
    return value


def _validate_choice(value: Any, allowed: set[str], *, where: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{where} must be one of {sorted(allowed)}, got {value!r}")
    return value


def _reject_unsafe_path(value: str, *, where: str) -> str:
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts:
        raise ConfigError(
            f"{where} must be a relative path inside the workspace "
            f"(no leading '/', no '..'), got {value!r}"
        )
    return value


def _validate_str_list(value: Any, *, where: str) -> list[str]:
    if not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        raise ConfigError(f"{where} must be a list of strings, got {value!r}")
    return list(value)


@dataclass
class ScopeOverride:
    enabled: bool = True
    gomod_path: str | None = None
    update_runtime: bool = False
    min_severity: str | None = None
    runtime_eol_lead_days: int | None = None
    update_freshness: bool = False
    freshness_level: str | None = None
    freshness_group: str | None = None
    freshness_include: list[str] = field(default_factory=list)
    freshness_exclude: list[str] = field(default_factory=list)


@dataclass
class CustomScope:
    name: str
    kind: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Defaults:
    pr_labels: list[str] = field(default_factory=lambda: ["dependencies", "automated"])
    min_severity: str | None = None
    runtime_eol_lead_days: int = 30
    freshness_level: str = "range"
    freshness_group: str = "scope"


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
        min_sev = spec.get("min_severity")
        if min_sev is not None and min_sev not in SEVERITY_ORDER:
            raise ConfigError(
                f"scopes.{name}.min_severity must be one of {SEVERITY_ORDER}, got {min_sev!r}"
            )
        lead = spec.get("runtime_eol_lead_days")
        if lead is not None:
            lead = _validate_lead_days(lead, where=f"scopes.{name}")
        f_level = spec.get("freshness_level")
        if f_level is not None:
            f_level = _validate_choice(
                f_level, _FRESHNESS_LEVELS, where=f"scopes.{name}.freshness_level"
            )
        f_group = spec.get("freshness_group")
        if f_group is not None:
            f_group = _validate_choice(
                f_group, _FRESHNESS_GROUPS, where=f"scopes.{name}.freshness_group"
            )
        f_include = spec.get("freshness_include")
        f_include = (
            _validate_str_list(f_include, where=f"scopes.{name}.freshness_include")
            if f_include is not None
            else []
        )
        f_exclude = spec.get("freshness_exclude")
        f_exclude = (
            _validate_str_list(f_exclude, where=f"scopes.{name}.freshness_exclude")
            if f_exclude is not None
            else []
        )
        gomod = spec.get("gomod_path")
        if gomod is not None:
            _reject_unsafe_path(str(gomod), where=f"scopes.{name}.gomod_path")
        cfg.scopes[name] = ScopeOverride(
            enabled=bool(spec.get("enabled", True)),
            gomod_path=gomod,
            update_runtime=bool(spec.get("update_runtime", False)),
            min_severity=min_sev,
            runtime_eol_lead_days=lead,
            update_freshness=bool(spec.get("update_freshness", False)),
            freshness_level=f_level,
            freshness_group=f_group,
            freshness_include=f_include,
            freshness_exclude=f_exclude,
        )

    for i, raw in enumerate(data.get("custom") or []):
        if not isinstance(raw, dict):
            raise ConfigError(f"custom[{i}] must be a table")
        missing = _REQUIRED_CUSTOM - raw.keys()
        if missing:
            raise ConfigError(f"custom[{i}]: missing required key(s): {sorted(missing)}")
        kind = str(raw["kind"])
        required_extra = _REQUIRED_CUSTOM_EXTRA.get(kind, set())
        missing_extra = required_extra - raw.keys()
        if missing_extra:
            raise ConfigError(
                f"custom[{i}] (kind={kind!r}): missing required key(s): {sorted(missing_extra)}"
            )
        target_file = raw.get("target_file")
        if isinstance(target_file, str):
            _reject_unsafe_path(target_file, where=f"custom[{i}].target_file")
        cfg.custom.append(
            CustomScope(
                name=str(raw["name"]),
                kind=kind,
                extra={k: v for k, v in raw.items() if k not in _REQUIRED_CUSTOM},
            )
        )

    defaults = data.get("defaults") or {}
    if defaults:
        _reject_unknown(defaults, _ALLOWED_DEFAULTS, where="defaults")
        labels = defaults.get("pr_labels")
        if labels is not None:
            if not (isinstance(labels, list) and all(isinstance(x, str) for x in labels)):
                raise ConfigError("defaults.pr_labels must be a list of strings")
            cfg.defaults.pr_labels = list(labels)
        min_sev = defaults.get("min_severity")
        if min_sev is not None and min_sev not in SEVERITY_ORDER:
            raise ConfigError(
                f"defaults.min_severity must be one of {SEVERITY_ORDER}, got {min_sev!r}"
            )
        cfg.defaults.min_severity = min_sev
        lead = defaults.get("runtime_eol_lead_days")
        if lead is not None:
            cfg.defaults.runtime_eol_lead_days = _validate_lead_days(lead, where="defaults")
        d_level = defaults.get("freshness_level")
        if d_level is not None:
            cfg.defaults.freshness_level = _validate_choice(
                d_level, _FRESHNESS_LEVELS, where="defaults.freshness_level"
            )
        d_group = defaults.get("freshness_group")
        if d_group is not None:
            cfg.defaults.freshness_group = _validate_choice(
                d_group, _FRESHNESS_GROUPS, where="defaults.freshness_group"
            )

    return cfg


def effective_min_severity(config: Config, scope: str) -> str | None:
    override = config.scopes.get(scope)
    if override and override.min_severity is not None:
        return override.min_severity
    return config.defaults.min_severity


def update_runtime_enabled(config: Config, scope: str) -> bool:
    override = config.scopes.get(scope)
    return override.update_runtime if override else False


def effective_runtime_eol_lead_days(config: Config, scope: str) -> int:
    override = config.scopes.get(scope)
    if override and override.runtime_eol_lead_days is not None:
        return override.runtime_eol_lead_days
    return config.defaults.runtime_eol_lead_days


def update_freshness_enabled(config: Config, scope: str) -> bool:
    override = config.scopes.get(scope)
    return override.update_freshness if override else False


def effective_freshness_level(config: Config, scope: str) -> str:
    override = config.scopes.get(scope)
    if override and override.freshness_level is not None:
        return override.freshness_level
    return config.defaults.freshness_level


def effective_freshness_group(config: Config, scope: str) -> str:
    override = config.scopes.get(scope)
    if override and override.freshness_group is not None:
        return override.freshness_group
    return config.defaults.freshness_group


def freshness_filters(config: Config, scope: str) -> tuple[list[str], list[str]]:
    override = config.scopes.get(scope)
    if not override:
        return [], []
    return list(override.freshness_include), list(override.freshness_exclude)


def _reject_unknown(data: dict, allowed: set[str], *, where: str) -> None:
    extras = set(data.keys()) - allowed
    if extras:
        raise ConfigError(f"{where}: unknown key(s): {sorted(extras)} (allowed: {sorted(allowed)})")
