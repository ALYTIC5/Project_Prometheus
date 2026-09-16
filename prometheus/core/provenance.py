"""Resolving the exact code version an experiment ran against.

CLAUDE.md: every backtest must be "bit-reproducible from (data_version,
code_sha, config_hash, seed)". An experiment whose code_sha cannot be
resolved is not reproducible, and writing "unknown" into that column would
claim reproducibility that does not exist -- so code_sha() raises instead
of falling back to a placeholder, the same posture RiskLimits takes on a
missing env var.
"""
from __future__ import annotations

import subprocess


class CodeShaUnresolvable(Exception):
    pass


def code_sha() -> str:
    """GIT_SHA / RAILWAY_GIT_COMMIT_SHA (set as a Docker build arg / by
    Railway's build environment) take priority over a local `git`
    invocation, because the deployed container has no .git directory --
    see the Dockerfile, which must pass GIT_SHA at build time."""
    import os

    for var in ("GIT_SHA", "RAILWAY_GIT_COMMIT_SHA"):
        value = os.environ.get(var)
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise CodeShaUnresolvable(
            "no GIT_SHA/RAILWAY_GIT_COMMIT_SHA env var and `git rev-parse HEAD` failed -- "
            "an experiment cannot be recorded without a resolvable code version"
        ) from exc
    return result.stdout.strip()
