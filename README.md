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

Sentinel coexists with Dependabot. Dependabot answers *"is there a newer
version?"*. Sentinel answers *"is there a current vulnerability with a
known fix, and what's the minimum change that closes it?"*

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
      - uses: actions/checkout@v4
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
      - uses: actions/checkout@v4
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

## How sentinel differs from Dependabot

| Dimension | Dependabot | sentinel |
|---|---|---|
| What it touches | Dep manifest versions | All of that + language runtime pins + vendor pins + OSV ignore lists |
| Trigger | Schedule; picks latest | Schedule; picks **minimum** version that closes an OSV advisory |
| Ignore lists | Manual `dependabot.yml` block | Reads + cleans `osv-scanner.toml` / `deny.toml` |
| PR rationale | Generic | Cites advisory ID + summary + cleared suppressions |
| Custom registry tracking | Hardcoded ecosystems | `gh-release-pin` (more `target_kind`s coming) |

## License

[Apache-2.0](LICENSE).
