from datetime import date
from pathlib import Path

import scripts.scope_docker as sd
from scripts.config import Config, ScopeOverride
from scripts.scope_docker import (
    bump_from_line,
    bump_tag,
    find_dockerfiles,
    parse_from,
    parse_tag,
    scan,
)


def test_parse_from_official_variants():
    assert parse_from("FROM python:3.8-slim").image == "python"
    assert parse_from("FROM library/node:18").image == "node"
    assert parse_from("FROM docker.io/library/python:3.8").image == "python"
    assert parse_from("FROM --platform=$BUILDPLATFORM node:18 AS build").image == "node"


def test_parse_from_non_official_and_specials():
    assert parse_from("FROM ghcr.io/org/python:3.8").image is None
    assert parse_from("FROM myorg/node:18").image is None
    assert parse_from("FROM scratch").image is None
    assert parse_from("FROM build").image is None  # stage ref
    assert parse_from("FROM ${BASE}").image is None
    assert parse_from("RUN echo FROM python") is None  # not a FROM line
    assert parse_from("# FROM python:3.8") is None  # comment


def test_parse_from_tag_and_digest():
    r = parse_from("FROM python:3.8")
    assert r.tag == "3.8" and r.has_digest is False
    r = parse_from("FROM python:3.8@sha256:abc")
    assert r.tag == "3.8" and r.has_digest is True
    assert parse_from("FROM python").tag is None


def test_parse_tag():
    assert parse_tag("3.8") == ("3.8", "")
    assert parse_tag("3.8-slim") == ("3.8", "-slim")
    assert parse_tag("18.16.0-bookworm") == ("18.16.0", "-bookworm")
    assert parse_tag("latest") is None
    assert parse_tag("slim") is None
    assert parse_tag("bookworm-slim") is None


def test_bump_tag_granularity_and_suffix():
    # python parts=2
    assert bump_tag("3.8", "-slim", "3.9", "3.9.20", parts=2) == "3.9-slim"
    assert bump_tag("3.8.10", "-bookworm", "3.9", "3.9.20", parts=2) == "3.9.20-bookworm"
    # node parts=1
    assert bump_tag("18", "-alpine", "20", "20.11.1", parts=1) == "20-alpine"
    assert bump_tag("18.16.0", "", "20", "20.11.1", parts=1) == "20.11.1"


def test_bump_from_line_minimal_diff():
    assert (
        bump_from_line("FROM python:3.8-slim AS base", "3.9-slim") == "FROM python:3.9-slim AS base"
    )
    assert bump_from_line("FROM --platform=$BUILDPLATFORM node:18 AS b", "20") == (
        "FROM --platform=$BUILDPLATFORM node:20 AS b"
    )


def test_find_dockerfiles_recursive_with_excludes(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.8\n")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "Dockerfile.prod").write_text("FROM node:18\n")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.Dockerfile").write_text("FROM node:18\n")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "Dockerfile").write_text("FROM python:3.8\n")
    (tmp_path / "notes.txt").write_text("x")

    found = {p.relative_to(tmp_path).as_posix() for p in find_dockerfiles(tmp_path)}
    assert found == {"Dockerfile", "api/Dockerfile.prod", "web/app.Dockerfile"}


def test_find_dockerfiles_sorted_and_empty(tmp_path: Path):
    assert find_dockerfiles(tmp_path) == []


_PY = [
    {"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.7", "lts": False},
    {"cycle": "3.9", "eol": "2027-10-31", "latest": "3.9.20", "lts": False},
    {"cycle": "3.8", "eol": "2024-10-07", "latest": "3.8.20", "lts": False},
]
_NODE = [
    {"cycle": "22", "eol": "2027-04-30", "latest": "22.1.0", "lts": "2024-10-29"},
    {"cycle": "20", "eol": "2026-04-30", "latest": "20.11.1", "lts": "2023-10-24"},
    {"cycle": "18", "eol": "2025-04-30", "latest": "18.20.1", "lts": "2022-10-25"},
]
_TODAY = date(2026, 1, 1)


def _fetch(product):
    return _PY if product == "python" else _NODE


def test_scan_bumps_and_skips(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.8-slim AS build\n"
        "FROM node:18 AS run\n"
        "FROM python:3.12\n"  # current -> skip
        "FROM ghcr.io/org/python:3.8\n"  # non-official -> skip
        "FROM python:latest\n"  # no numeric -> skip
    )
    edits, manual = scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    news = sorted(e["new"] for e in edits)
    assert news == ["FROM node:20 AS run", "FROM python:3.9-slim AS build"]
    assert manual == []


def test_scan_digest_pinned_is_manual(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.8@sha256:abc\n")
    edits, manual = scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    assert edits == []
    assert manual == [{"file": "Dockerfile", "image": "python", "tag": "3.8"}]


def test_scan_fail_closed_on_fetch_error(tmp_path):
    from scripts.runtime_eol import RuntimeEolError

    (tmp_path / "Dockerfile").write_text("FROM python:3.8\n")

    def boom(_product):
        raise RuntimeEolError("down")

    edits, manual = scan(tmp_path, lead_days=30, today=_TODAY, fetch=boom)
    assert edits == [] and manual == []


def _cfg_on():
    return Config(scopes={"docker": ScopeOverride(update_runtime=True)})


def test_run_opted_out_returns_empty_without_fetch(tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_text("FROM python:3.8\n")

    def boom(_p):
        raise AssertionError("must not fetch when opted out")

    monkeypatch.setattr(sd, "fetch_cycles", boom)
    assert sd.run(tmp_path, Config(), None, dry_run=True) == []


def test_run_opted_in_opens_pr_dry_run(tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_text("FROM python:3.8-slim\n")
    monkeypatch.setattr(sd, "_today", lambda: _TODAY)
    monkeypatch.setattr(sd, "fetch_cycles", _fetch)
    results = sd.run(tmp_path, _cfg_on(), None, dry_run=True)
    assert len(results) == 1 and results[0].kind == "noop"  # dry-run


def test_run_digest_opens_issue(tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_text("FROM python:3.8@sha256:abc\n")
    monkeypatch.setattr(sd, "_today", lambda: _TODAY)
    monkeypatch.setattr(sd, "fetch_cycles", _fetch)
    results = sd.run(tmp_path, _cfg_on(), None, dry_run=True)
    assert any(r.key == "docker-eol-digest" for r in results)


def test_apply_rewrites_files_real_mode(tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python:3.8-slim AS build\nRUN echo hi\nFROM node:18 AS run\n")
    edits, _ = sd.scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    plan = sd._plan(tmp_path, edits)
    for step in plan.post_steps:
        step()
    # only the two FROM lines change; the RUN line and trailing newline are preserved
    assert df.read_text() == "FROM python:3.9-slim AS build\nRUN echo hi\nFROM node:20 AS run\n"


def test_apply_preserves_crlf(tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_bytes(b"FROM python:3.8\r\nRUN echo hi\r\n")
    edits, _ = sd.scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    plan = sd._plan(tmp_path, edits)
    for step in plan.post_steps:
        step()
    assert df.read_bytes() == b"FROM python:3.9\r\nRUN echo hi\r\n"


def test_scan_skips_unreadable_file(tmp_path):
    (tmp_path / "bin.Dockerfile").write_bytes(b"\xff\xfe\x00\x01")  # not valid UTF-8
    (tmp_path / "Dockerfile").write_text("FROM python:3.8\n")
    edits, manual = sd.scan(tmp_path, lead_days=30, today=_TODAY, fetch=_fetch)
    # binary file skipped (no crash); the valid Dockerfile still bumped
    assert [e["file"] for e in edits] == ["Dockerfile"]
    assert manual == []
