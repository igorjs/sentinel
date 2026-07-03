# Sentinel

> Auto-PRs that patch vulnerable dependencies, driven by the [OSV](https://osv.dev) database, across Rust, Go, JavaScript, and Python.

[![CI](https://github.com/igorjs/sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/igorjs/sentinel/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/igorjs/sentinel?sort=semver)](https://github.com/igorjs/sentinel/releases)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/igorjs/sentinel/badge)](https://securityscorecards.dev/viewer/?uri=github.com/igorjs/sentinel)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Sentinel watches your dependencies with OSV. When a fix lands for a known advisory, it opens a pull request that bumps to the minimum version closing it. You review, you merge, nothing auto-merges. It covers what Dependabot's security updates leave out: OSV's wider advisory set (RUSTSEC, Go, and PyPI natively), language-runtime pins, vendored release pins, and self-cleaning suppression lists.

## Highlights

- **OSV-driven security bumps** across Rust, Go, npm, and PyPI, to the minimum version that closes the advisory.
- **More than dep versions**: raises end-of-life language runtimes, Docker base images, and CI version matrices, and re-pins vendored release artefacts.
- **Self-cleaning**: strips stale `osv-scanner.toml` / `deny.toml` ignore entries once a bump retires them.
- **Safe by default**: every change is a PR you review, and a `min_severity` gate keeps the noise down.
- **No Dependabot overlap**: security-fix bumps only; routine freshness stays Dependabot's job, or opt in per scope.

## Quick start

Create `.github/workflows/sentinel.yml`:

```yaml
name: Sentinel
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
      - uses: igorjs/sentinel/discover@v1
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
      - uses: igorjs/sentinel@v1
        with:
          scope: ${{ matrix.scope }}
          dry_run: ${{ inputs.dry_run || false }}
```

No config file needed for a default repo layout. The `discover` job auto-detects which scopes apply and fans the `run` job out over them.

## Scopes

Sentinel picks the scopes that apply from the files in your repo.

| Scope | Detected by | What it bumps | Runtime EOL |
|---|---|---|---|
| `rust` | `Cargo.lock` | Cargo deps via `cargo update --precise`, self-cleans `osv-scanner.toml` / `deny.toml` | N/A |
| `go` | `go.mod` | Module deps via `go get` + `go mod tidy`, optionally the `go <version>` directive | On by default |
| `javascript` | `package.json` | npm deps via npm / pnpm / yarn (lockfile-detected) | Opt-in |
| `python` | `pyproject.toml`, `requirements.txt`, or a lockfile | PyPI deps via poetry / uv / pipenv (lockfile-detected) | Opt-in |
| `docker` | `Dockerfile` (recursive) | EOL `python` / `node` base-image tags | Opt-in |
| `ci` | `.github/workflows/*.yml` | EOL `python-version` / `node-version` matrices and runner OS labels | Opt-in |

A repo without a lockfile gets a "no lockfile" issue instead of a risky bump.

## Configuration

Everything below is optional and lives in `.github/sentinel.toml`.

<details>
<summary><b>Severity gating</b></summary>

By default Sentinel acts on every fixable advisory. To act only at or above a severity, set `min_severity` (`none`, `low`, `medium`, `high`, `critical`) globally or per scope:

```toml
[defaults]
min_severity = "high"      # global floor

[scopes.javascript]
min_severity = "critical"  # stricter for one scope
```

Severity comes from the CVSS score `osv-scanner` reports. Advisories with no severity data are bumped anyway (the PR says so), so a serious-but-unscored CVE is never silently skipped. `gh-release-pin` scopes are freshness-driven and aren't gated.
</details>

<details>
<summary><b>Runtime EOL bumps (opt-in)</b></summary>

Set `update_runtime = true` on a scope to open PRs that raise an end-of-life (or near-EOL) runtime to the oldest still-supported version. EOL dates come from [endoflife.date](https://endoflife.date), and these PRs ignore `min_severity`. `runtime_eol_lead_days` (default `30`) opens the PR that many days before the EOL date.

- **Python** reads `requires-python`, `.python-version`, `.tool-versions`, and mise configs.
- **Node** reads `engines.node`, `.nvmrc`, `.node-version`, `.tool-versions`, and mise configs.
- **Docker** (`[scopes.docker]`) raises EOL `python` / `node` base-image tags, preserving the variant suffix (`-slim`, `-alpine`, ...); digest-pinned bases are reported in an issue, not edited.
- **CI** (`[scopes.ci]`) rewrites EOL `python-version` / `node-version` matrices and EOL runner OS labels (`runs-on:`, `strategy.matrix.os:`), preserving quoting and comments; `*-latest` and `${{ ... }}` are left alone.

When a floor bump touches `requires-python` or `engines.node`, Sentinel refreshes the matching lockfile so the recorded constraint stays consistent, or opens an issue if the package manager isn't available.
</details>

<details>
<summary><b>Version freshness (opt-in)</b></summary>

Set `update_freshness = true` on the `javascript` scope to bump outdated npm deps to the newest version within their declared range. It runs separately from security bumps, on the `sentinel/javascript/freshness` branch.

- `freshness_level`: `range` (default) stays within the constraint; `major` crosses it to the absolute latest.
- `freshness_group`: `scope` (default) is one PR; `dependency` is one PR per dep.
- `freshness_include` / `freshness_exclude`: dependency-name globs (exclude wins) to avoid overlapping with Dependabot.

If `.github/dependabot.yml` exists, the PR notes it. Slice 1 covers npm; pnpm/yarn and the other ecosystems follow.
</details>

<details>
<summary><b>Custom vendor pins (gh-release-pin)</b></summary>

For a vendored artefact pinned in a workflow YAML, declare a `gh-release-pin` custom scope:

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

Sentinel opens a PR when upstream cuts a newer release.
</details>

<details>
<summary><b>Suppression recovery</b></summary>

`osv-scanner` hides advisories listed in `osv-scanner.toml`'s `IgnoredVulns`, so Sentinel runs a second scan that bypasses the ignore list. If an advisory you suppressed (say, when no fix existed) now has one, Sentinel opens a normal bump PR, and the `rust` scope's PR strips the now-removable `osv-scanner.toml` / `deny.toml` entry. A human still reviews it, so a deliberately-kept suppression can be declined.
</details>

## Sentinel vs Dependabot

Dependabot already does CVE-driven security updates to the minimum patched version. Sentinel overlaps there and differs on the rest:

| Dimension | Dependabot | Sentinel |
|---|---|---|
| Advisory source | GitHub Advisory Database | OSV (RUSTSEC, Go, PyPI, npm, crates.io, ...) |
| Freshness updates | Yes, picks latest | No, left to Dependabot (or opt in) |
| Security updates | Yes, minimum patched version | Yes, minimum version that closes the OSV advisory |
| Beyond dep versions | None | Language-runtime pins + `gh-release-pin` vendor pins |
| Suppression lists | Manual `dependabot.yml` block | Reads and self-cleans `osv-scanner.toml` / `deny.toml` |
| Severity gating | Not configurable per run | `min_severity` (global and per-scope) |

## License

[Apache-2.0](LICENSE).
</content>
