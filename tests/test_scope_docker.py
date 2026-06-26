from scripts.scope_docker import bump_from_line, bump_tag, parse_from, parse_tag


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
