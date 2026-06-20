"""Shared dataclasses used across all scopes."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Drift:
    scope: str
    key: str
    summary: str
    fixed_versions: list[str]
    current: str
    raw: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def __hash__(self) -> int:
        return hash((self.scope, self.key))


@dataclass(frozen=True)
class Plan:
    scope: str
    key: str
    branch: str
    title: str
    body: str
    files_changed: list[str]
    commands: list[list[str]]
    post_steps: tuple[Callable[[], None], ...] = ()


@dataclass(frozen=True)
class Result:
    scope: str
    key: str
    kind: Literal["pr", "issue", "noop"]
    summary: str
