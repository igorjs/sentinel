# sentinel

Generic GitHub Action that opens auto-PRs for OSV-driven dependency bumps
across rust, go, javascript, python, and custom upstream-release pins.
Self-cleans `osv-scanner.toml` / `deny.toml` ignore lists when bumps
retire their entries.

**Status:** v1 — production-ready for the four built-in language scopes
and the `gh-release-pin` custom scope. v2 adds Docker / pre-commit / npm-engine bumps.

## What sentinel does (and doesn't)

- ✅ Bumps cargo deps when OSV reports a fix is available
- ✅ Bumps go module deps + optionally the `go <version>` runtime directive
- ✅ Bumps npm deps via npm/pnpm/yarn (lockfile-detected)
- ✅ Bumps PyPI deps via poetry/uv/pipenv (lockfile-detected)
- ✅ Bumps pinned vendor versions when upstream cuts a new release
- ✅ Removes ignore entries from `osv-scanner.toml` / `deny.toml` when bumps close them
- ❌ Auto-merging PRs (every PR is reviewed by a human)
- ❌ Routine "is there a newer version?" freshness bumps (that's Dependabot's job)

Sentinel overlaps with Dependabot's *security updates* — both bump to the
minimum version that closes an advisory — and complements them. Sentinel adds
what Dependabot doesn't: OSV's broader advisory coverage (RUSTSEC, Go, and PyPI
natively, not only the GitHub Advisory Database), language-runtime pins (the `go`
directive), vendored `gh-release-pin` artefacts, self-cleaning of
`osv-scanner.toml` / `deny.toml` suppression lists, and a configurable
`min_severity` gate. It deliberately leaves routine "is there a newer version?"
freshness bumps to Dependabot's version updates.

## Quick start

In your repo, create `.github/workflows/sentinel.yml`:

```yaml
name: sentinel
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays 06:00 UTC
  workflow_dispatch:
    inputs:
      dry_run:
        type: boolean
        default: false

permissions:
  contents: write
  pull-requests: write
  issues: write

concurrency:
  group: sentinel
  cancel-in-progress: true

jobs:
  discover:
    runs-on: ubuntu-latest
    outputs:
      scopes: ${{ steps.s.outputs.scopes }}
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
      - uses: igorjs/sentinel/discover@v0.1
        id: s

  run:
    needs: discover
    if: needs.discover.outputs.scopes != '[]'
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        scope: ${{ fromJson(needs.discover.outputs.scopes) }}
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
      - uses: igorjs/sentinel@v0.1
        with:
          scope: ${{ matrix.scope }}
          dry_run: ${{ inputs.dry_run || false }}
```

No config file needed for a default repo layout.

## Built-in scopes (auto-detected)

| Scope | Trigger file | What it bumps | Runtime bump |
|---|---|---|---|
| `rust` | `Cargo.lock` | Cargo deps via `cargo update --precise` + self-cleans `osv-scanner.toml` / `deny.toml` | N/A |
| `go` | `go.mod` (any path) | Module deps via `go get` + `go mod tidy`. Optionally bumps `go <version>` runtime directive for stdlib advisories. | Default ON; `[scopes.go] update_runtime = false` to opt out |
| `javascript` | `package.json` | npm deps via npm/pnpm/yarn (auto-detected from lockfile) | N/A (deferred to v0.2) |
| `python` | `pyproject.toml` / `requirements.txt` / lockfile | PyPI deps via poetry/uv/pipenv (auto-detected from lockfile) | N/A (deferred to v0.2) |
| `docker` | `Dockerfile` (and variants, recursively) | Base-image tags for python / node | Opt-in; `[scopes.docker] update_runtime = true` |
| `ci` | `.github/workflows/*.yml` | End-of-life matrix entries (python-version / node-version) in GitHub Actions workflows | Opt-in; `[scopes.ci] update_runtime = true` |

Lockfile-less repos surface a "no lockfile" issue rather than risk a broken bump.

## Custom scopes

For vendored artefacts pinned in a workflow YAML, declare a
`gh-release-pin` custom scope in `.github/sentinel.toml`:

```toml
[[custom]]
name = "libkrun-bottle"
kind = "gh-release-pin"
upstream_repo = "igorjs/libkrun-builds"
target_file = ".github/workflows/release.yml"
target_kind = "yaml-env-var"
env_var = "LIBKRUN_BOTTLE_VERSION"
# env_path = "jobs.publish.env"   # optional; default "env" (top-level)
```

## Severity gating

By default sentinel acts on every fixable advisory. To act only at or above a
severity, set `min_severity` (one of `none`, `low`, `medium`, `high`,
`critical`) globally or per scope in `.github/sentinel.toml`:

```toml
[defaults]
min_severity = "high"      # global floor

[scopes.javascript]
min_severity = "critical"  # stricter for one scope
```

Severity comes from the CVSS score `osv-scanner` reports for the advisory.
Advisories with no severity data are bumped anyway (and the PR says so), so a
serious-but-unscored CVE is never silently skipped. `gh-release-pin` scopes are
freshness-driven and are not gated.

## Runtime EOL bumps (opt-in)

Set `update_runtime = true` on a `python` or `javascript` scope to also open PRs
that raise an end-of-life (or near-EOL) runtime declaration to the oldest
still-supported version. EOL dates come from endoflife.date. These PRs are
independent of `min_severity`.

- Python: `requires-python` (pyproject.toml), `.python-version`, `.tool-versions` (asdf/mise), and mise configs (`mise.toml`, `.mise.toml`, `.config/mise/config.toml`)
- Node: `engines.node` (package.json), `.nvmrc`, `.node-version`, `.tool-versions` (asdf/mise), and mise configs (`mise.toml`, `.mise.toml`, `.config/mise/config.toml`)

### Docker base images (opt-in)

Set `update_runtime = true` on a `docker` scope to scan Dockerfiles
(`Dockerfile`, `Dockerfile.*`, `*.Dockerfile`, recursively) and open a PR raising
end-of-life official `python` / `node` base-image tags to the oldest still-supported
version (e.g. `FROM python:3.8-slim` → `FROM python:3.9-slim`). The variant suffix
(`-slim`, `-alpine`, `-bookworm`, …) is preserved. Digest-pinned bases
(`python:3.8@sha256:…`) are reported in an issue instead of edited. EOL dates come
from endoflife.date.

`runtime_eol_lead_days` (default `30`, per-scope or under `[defaults]`) opens the
PR that many days before the EOL date. `update_runtime` defaults to `false`.
When a floor bump touches `requires-python` or `engines.node`, sentinel also refreshes the matching lockfile (`uv.lock`, `poetry.lock`, `Pipfile.lock`, or `package-lock.json`) so the recorded runtime constraint stays consistent. If the package manager isn't available, it opens an issue instead.

### CI version matrices (opt-in)

Set `update_runtime = true` on a `ci` scope to scan `.github/workflows/*.yml` and
open a PR replacing end-of-life `python-version` / `node-version` matrix entries with
the oldest still-supported version (e.g. `python-version: ["3.8", "3.10"]` →
`["3.9", "3.10"]`). EOL entries are dropped when supported versions remain, an all-EOL
list collapses to the oldest supported (never empty), and quoting/comments are
preserved. EOL dates come from endoflife.date. (Runner-OS bumping, e.g. `runs-on:
ubuntu-20.04`, is not yet covered.)

## Suppression recovery

`osv-scanner` hides advisories listed in `osv-scanner.toml`'s `IgnoredVulns`, so
sentinel runs a second scan that bypasses that ignore list. If an advisory you
suppressed (e.g. when no fix existed) now has a fix, sentinel opens a normal
bump PR for it — and the `rust` scope's PR also strips the now-removable
`osv-scanner.toml` / `deny.toml` entry. As with every sentinel PR, a human
reviews it, so a deliberately-kept suppression can simply be declined.

## How sentinel differs from Dependabot

Dependabot already does CVE-driven *security updates* to the minimum patched
version. Sentinel overlaps there and differs on the rest:

| Dimension | Dependabot | sentinel |
|---|---|---|
| Advisory source | GitHub Advisory Database | OSV (RUSTSEC, Go, PyPI, npm, crates.io, ...) |
| Version (freshness) updates | Yes — picks latest | No — left to Dependabot |
| Security updates | Yes — minimum patched version | Yes — minimum version that closes the OSV advisory |
| Beyond dep versions | — | Language runtime pins + `gh-release-pin` vendor pins |
| Suppression lists | Manual `dependabot.yml` block | Reads + self-cleans `osv-scanner.toml` / `deny.toml` |
| Severity gating | Not configurable per-run | `min_severity` (global + per-scope) |

## License

[Apache-2.0](LICENSE).
