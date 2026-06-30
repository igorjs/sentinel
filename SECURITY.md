# Security Policy

## Supported versions

Sentinel is pre-1.0. Security fixes land on `main` and in the latest `v0.x`
release. Pin to a released tag (`igorjs/sentinel@v0`) or a commit SHA; older
tags do not receive backported fixes.

## Reporting a vulnerability

Please report security issues privately, not via public issues or pull
requests.

- Use GitHub's private reporting: the repository's Security tab, then
  Report a vulnerability (GitHub Security Advisories).

Include enough to reproduce: affected version/SHA, a minimal repro, the impact,
and any suggested fix.

### What to expect

- Acknowledgement within 5 business days.
- An initial assessment (severity, affected versions) within 10 business
  days.
- Coordinated disclosure: we agree on a timeline before any public detail, and
  credit reporters who want it.

## Scope

In scope: the action itself, the Python in `scripts/`, the composite actions
(`action.yml`, `discover/action.yml`), how it invokes `osv-scanner` / `gh` /
package managers, and how advisory data flows into commands, branches, and PRs.

Out of scope: vulnerabilities in `osv-scanner`, `gh`, GitHub Actions, or the
package managers themselves (report those upstream), and findings in a
consumer's own repository surfaced by sentinel (that is sentinel working as
intended).

## Hardening notes

- Sentinel runs with the permissions the consumer's workflow grants it
  (typically `contents: write`, `pull-requests: write`, `issues: write`). Review
  every PR it opens; it never auto-merges.
- The action pins `osv-scanner` by version and verifies its SHA-256, pins its
  Python dependencies, and SHA-pins the third-party actions it uses.
- Advisory-sourced package names and versions are validated before they reach a
  package manager command line.
