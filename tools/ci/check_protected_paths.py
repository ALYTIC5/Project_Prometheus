"""CI guard: the automated research loop may never change the evaluator.

A third, independent layer beside the research DB role (migration 0024)
and the law tests (tests/laws/). Fails when any commit in the checked
range was made on the research-policy branch OR authored by the loop's
own git identity, and touches a protected path:

- prometheus/validation/          judging, holdout reader, status gate,
                                  canary registry, (future) discovery gate
- prometheus/experiments/violations.py   the research-violation log
- prometheus/core/config.py       risk limits (Law 4)
- config/holdout.yaml             the holdout boundary (Law 3)
- alembic/                        every migration, DB roles included
- tests/laws/                     the laws' own tests
- CLAUDE.md                       the laws' text
- .github/, tools/ci/             this guard itself

Humans committing on other branches are unaffected -- those changes go
through normal review.

Usage: python -m tools.ci.check_protected_paths --base <sha> --head <sha> --branch <name>
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass

POLICY_BRANCH = "research-policy"
LOOP_AUTHOR_EMAIL = "research-loop@prometheus.invalid"
PROTECTED_PREFIXES = (
    "prometheus/validation/",
    "prometheus/experiments/violations.py",
    "prometheus/core/config.py",
    "config/holdout.yaml",
    "alembic/",
    "tests/laws/",
    "CLAUDE.md",
    ".github/",
    "tools/ci/",
)
_NULL_SHA = "0" * 40


@dataclass(frozen=True)
class Offence:
    sha: str
    author: str
    path: str


def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def is_protected(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in PROTECTED_PREFIXES)


def commits_in_range(base: str | None, head: str, cwd: str | None = None) -> list[str]:
    """base..head; a missing or all-zero base (a new branch) means every
    commit on head that is not on main."""
    new_branch = not base or base == _NULL_SHA
    spec = [head, "--not", "origin/main"] if new_branch else [f"{base}..{head}"]
    return [line for line in _git("rev-list", *spec, cwd=cwd).splitlines() if line]


def find_offences(
    base: str | None, head: str, branch: str, cwd: str | None = None
) -> list[Offence]:
    offences: list[Offence] = []
    for sha in commits_in_range(base, head, cwd=cwd):
        author = _git("show", "-s", "--format=%ae", sha, cwd=cwd).strip()
        if branch != POLICY_BRANCH and author != LOOP_AUTHOR_EMAIL:
            continue
        changed = _git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", sha, cwd=cwd
        ).splitlines()
        offences.extend(Offence(sha, author, p) for p in changed if p and is_protected(p))
    return offences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args(argv)
    offences = find_offences(args.base, args.head, args.branch)
    for o in offences:
        print(f"PROTECTED PATH: {o.path} changed by {o.author} in {o.sha[:12]}")
    if offences:
        print(
            f"{len(offences)} protected path change(s) by the automated research loop "
            f"(branch {POLICY_BRANCH!r} or author {LOOP_AUTHOR_EMAIL!r}). The loop may "
            "never change the evaluator, the laws, risk limits or DB roles."
        )
        return 1
    print("protected-path guard: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
