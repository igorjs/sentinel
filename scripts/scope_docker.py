"""docker scope: bump end-of-life official Python/Node base images in Dockerfiles."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

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
    return f"{m['prefix']}{m['image']}:{new_tag}{m['rest']}"
