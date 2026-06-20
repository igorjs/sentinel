"""Branch naming, git ops, idempotent PR/issue helpers for sentinel scopes."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from scripts.types import Plan, Result

_SAFE = re.compile(r"[^a-z0-9]+")
_BOT_NAME = "sentinel-bot"
_BOT_EMAIL = "sentinel@users.noreply.github.com"


def branch_name(scope: str, key: str) -> str:
    scope_slug = _SAFE.sub("-", scope.lower()).strip("-")
    key_slug = _SAFE.sub("-", key.lower()).strip("-")
    return f"sentinel/{scope_slug}/{key_slug}"


def capture_base_sha(workdir: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workdir,
        capture_output=True, check=True, text=True,
    ).stdout.strip()


def apply_plan(
    plan: Plan, *, dry_run: bool, workdir: Path, base_sha: str
) -> Result:
    if dry_run:
        print(f"[dry-run] would apply plan for {plan.scope}/{plan.key}")
        for cmd in plan.commands:
            print(f"[dry-run]   $ {' '.join(cmd)}")
        for step in plan.post_steps:
            print(f"[dry-run]   $ {step.__name__}")
        return Result(scope=plan.scope, key=plan.key, kind="noop",
                      summary=f"dry-run: {plan.title}")

    subprocess.run(["git", "switch", "-C", plan.branch, base_sha],
                   cwd=workdir, check=True)

    for cmd in plan.commands:
        subprocess.run(cmd, cwd=workdir, check=True)
    for step in plan.post_steps:
        step()

    # No-op detection: both tracked changes AND untracked files must be absent.
    diff_rc = subprocess.run(
        ["git", "diff", "--quiet", "HEAD"], cwd=workdir
    ).returncode
    untracked = subprocess.run(
        ["git", "status", "--porcelain"], cwd=workdir,
        capture_output=True, check=True, text=True,
    ).stdout.strip()
    if diff_rc == 0 and not untracked:
        return Result(scope=plan.scope, key=plan.key, kind="noop",
                      summary="no diff after apply")

    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", f"user.name={_BOT_NAME}",
         "-c", f"user.email={_BOT_EMAIL}",
         "commit", "-m", plan.title, "-m", plan.body],
        cwd=workdir, check=True,
    )
    subprocess.run(
        ["git", "push", "--force-with-lease", "origin", plan.branch],
        cwd=workdir, check=True,
    )

    existing = subprocess.run(
        ["gh", "pr", "list", "--head", plan.branch,
         "--state", "open", "--json", "number"],
        cwd=workdir, capture_output=True, check=True, text=True,
    ).stdout.strip() or "[]"
    open_prs = json.loads(existing)
    if open_prs:
        pr_num = str(open_prs[0]["number"])
        subprocess.run(
            ["gh", "pr", "edit", pr_num, "--body", plan.body],
            cwd=workdir, check=True,
        )
    else:
        subprocess.run(
            ["gh", "pr", "create",
             "--title", plan.title, "--body", plan.body,
             "--head", plan.branch,
             "--label", "dependencies", "--label", "automated"],
            cwd=workdir, check=True,
        )
    return Result(scope=plan.scope, key=plan.key, kind="pr", summary=plan.title)


def open_issue_fallback(
    *,
    scope: str,
    key: str,
    title: str,
    body: str,
    dry_run: bool,
    workdir: Path,
) -> Result:
    if dry_run:
        print(f"[dry-run] would open issue: {title}")
        return Result(scope=scope, key=key, kind="noop",
                      summary=f"dry-run issue: {title}")

    # Idempotency: skip create if open issue with same title exists.
    existing = subprocess.run(
        ["gh", "issue", "list", "--state", "open",
         "--search", title, "--json", "number,title"],
        cwd=workdir, capture_output=True, check=True, text=True,
    ).stdout.strip() or "[]"
    matches = [i for i in json.loads(existing) if i.get("title") == title]
    if matches:
        return Result(scope=scope, key=key, kind="noop",
                      summary=f"existing issue #{matches[0]['number']}")

    subprocess.run(
        ["gh", "issue", "create",
         "--title", title,
         "--body", body,
         "--label", "sentinel",
         "--label", "dependencies"],
        cwd=workdir, check=True,
    )
    return Result(scope=scope, key=key, kind="issue", summary=title)
