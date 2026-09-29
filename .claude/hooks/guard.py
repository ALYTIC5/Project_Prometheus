"""PreToolUse guard (CLAUDE.md Law 17, docs/BUILD_PLAN.md P0).

Reads the hook payload on stdin and denies:
- any edit of, or shell write to, a hard-protected file;
- `git push` to main, and any force-push;
- adding the owner-only `owner-approved` PR label;
- requests to our API's sealed routes (.claude/hooks/blocked_endpoints.txt).

Everything else passes untouched (no output). Deliberately conservative: a
shell command that merely MENTIONS a hard-protected file next to anything
write-like is denied -- read it with the Read tool instead.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HARD_PROTECTED = ("config/protected.yaml", "config/holdout.yaml")
API_HOSTS = (
    "projectprometheus-production.up.railway.app",
    "localhost:8000",
    "127.0.0.1:8000",
)
# Matched against " <lowercased command> ": word-like hints carry a leading
# space so e.g. " dd " never matches inside "git add ".
_WRITE_HINTS = (
    ">", " tee ", "sed -i", "perl -i", "set-content", "out-file", "add-content",
    "copy-item", "move-item", "remove-item", "rename-item", "new-item", "clear-content",
    " cp ", " mv ", " rm ", "truncate", "writealltext", "write_text", "write_bytes",
    "open(", "git checkout", "git restore", "git rm", "git mv", " dd ", " install ",
    " ln ", " chmod", " unlink",
)
_FORCE = re.compile(r"(^|\s)(--force(-with-lease)?(=\S*)?|-f|--mirror|--delete|-d)(\s|$)")
_PUSH = re.compile(r"\bgit\b[^|;&]*\bpush\b(?P<args>[^|;&]*)")


def _deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"guard.py (CLAUDE.md Law 17): {reason}",
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def _norm(path: str) -> str:
    return path.replace("\\", "/").lower()


def _touches_hard_protected(text: str) -> str | None:
    lowered = _norm(text)
    return next((p for p in HARD_PROTECTED if p in lowered), None)


def _current_branch() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _blocked_endpoints() -> list[str]:
    path = Path(__file__).with_name("blocked_endpoints.txt")
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def check_command(command: str) -> str | None:
    lowered = _norm(command)
    protected = _touches_hard_protected(command)
    if protected and any(hint in f" {lowered} " for hint in _WRITE_HINTS):
        return f"shell write to hard-protected {protected} (use config/protected.proposed.yaml)"
    for match in _PUSH.finditer(lowered):
        args = match.group("args")
        if _FORCE.search(args) or re.search(r"(^|\s)\+\S", args):
            return "force-push is never allowed"
        tokens = args.split()
        refspecs = [t for t in tokens if not t.startswith("-")][1:]  # after the remote
        if any(t == "main" or t.endswith(":main") or t.endswith("/main") for t in refspecs):
            return "push to main is never allowed (open a PR)"
        if not refspecs and _current_branch() == "main":
            return "push while on main is never allowed (open a PR)"
    if "owner-approved" in lowered and ("label" in lowered or "gh api" in lowered):
        return "only the owner adds the owner-approved label"
    if any(host in lowered for host in API_HOSTS):
        for endpoint in _blocked_endpoints():
            if endpoint in lowered:
                return f"request to sealed API route {endpoint} (Law 13)"
    return None


def check_edit(file_path: str) -> str | None:
    lowered = _norm(file_path)
    for protected in HARD_PROTECTED:
        if lowered == protected or lowered.endswith("/" + protected):
            return f"edit of hard-protected {protected} (use config/protected.proposed.yaml)"
    return None


def main() -> None:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    reason: str | None = None
    if tool in ("Bash", "PowerShell"):
        reason = check_command(str(tool_input.get("command", "")))
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        reason = check_edit(str(tool_input.get("file_path") or tool_input.get("notebook_path", "")))
    if reason:
        _deny(reason)


if __name__ == "__main__":
    main()
