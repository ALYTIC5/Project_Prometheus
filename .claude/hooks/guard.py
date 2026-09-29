"""Claude Code guard hook (CLAUDE.md Law 17, docs/BUILD_PLAN.md P0).

PreToolUse (default mode), for Bash/PowerShell/Edit/Write/MultiEdit/
NotebookEdit. Denies:
- any edit of a hard-protected file;
- any shell command that names a hard-protected file (or a glob/short
  name that could expand to one) unless it is a single read-only command
  -- an ALLOWLIST, because the ways to write a file are endless;
- `git push` to main (any spelling), any force-push, pushes while on main,
  unknown git subcommands (aliases) mentioning main, and ref updates of main
  through the GitHub API;
- adding the owner-only `owner-approved` label;
- requests to our API's sealed routes (.claude/hooks/blocked_endpoints.txt).

PostToolUse (`--post`): after every tool call, if a hard-protected file no
longer matches git HEAD, the result is flagged as a violation -- this
catches any write the PreToolUse heuristics missed (e.g. a script written
elsewhere first).

Fails CLOSED: any error in this script exits 2, which blocks the call.
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
# A hard-protected file named directly, by glob, or by an 8.3 short name.
_PROTECTED_MENTION = re.compile(
    r"(protected|holdout)[^\s/]*\.(ya?ml|[*?])"
    r"|(protec|holdou?)[^\s/]*[*?\[]"
    r"|(protec|holdou)~\d"
)
# Single read-only commands allowed to NAME a protected file.
_READ_ONLY = re.compile(
    r"^\s*(git\s+(diff|show|log|status|add|commit|blame|grep|ls-files|check-ignore)\b"
    r"|cat|type|get-content|gc|less|more|head|tail|wc|grep|rg|select-string|sls|diff"
    r"|(\S*python(\.exe)?|\S*pytest(\.exe)?)\s+(-m\s+pytest|\S*pytest)\b)"
)
_CHAINING = re.compile(r"[;&|`>]|\$\(|\n")
_KNOWN_GIT = frozenset(
    "status diff log show add commit switch checkout branch fetch pull merge rebase stash "
    "tag rev-parse rev-list merge-base cherry-pick restore rm mv remote config ls-files "
    "ls-remote grep blame check-ignore worktree reset clean init clone describe shortlog "
    "notes reflog bisect apply am format-patch push".split()
)


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


def _norm_path(path: str) -> str:
    """Lowercase, forward slashes, no ./ or // segments, no trailing dots,
    spaces or NTFS stream suffixes."""
    p = path.replace("\\", "/").lower().strip()
    p = p.split("::")[0].rstrip(". ")
    while "/./" in p or "//" in p:
        p = p.replace("/./", "/").replace("//", "/")
    return p


def _norm_command(command: str) -> str:
    """Lowercase, and strip quotes and escapes so ma''in, "main" and ma\\in
    all read as main."""
    c = command.replace("\\", "").replace("'", "").replace('"', "").lower()
    while "/./" in c or "//" in c:
        c = c.replace("/./", "/").replace("//", "/")
    return c


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


def _is_main_ref(token: str) -> bool:
    return token in ("main", "refs/heads/main") or token.endswith((":main", ":refs/heads/main"))


def _mentions_protected(text: str) -> bool:
    # The sanctioned proposal file (Law 17) is not protected.
    return bool(_PROTECTED_MENTION.search(text.replace("protected.proposed.yaml", "")))


def _check_git(c: str) -> str | None:
    if re.search(r"\bgit\b.*\bpush\b", c) and ("$(" in c or "`" in c):
        return "git push built with command substitution is never allowed"
    for segment in re.split(r"[;&|\n]|\$\(|`", c):
        tokens = segment.split()
        if "git" not in tokens:
            continue
        args = tokens[tokens.index("git") + 1:]
        while args and args[0] in ("-c", "-C"):  # git -c k=v / -C dir
            args = args[2:]
        if not args:
            continue
        sub, rest = args[0], args[1:]
        if sub == "push" or (sub.startswith("alias") and "push" in segment):
            for t in rest:
                if t.startswith("--force") or t in ("--mirror", "--delete", "-d"):
                    return "force-push / ref deletion is never allowed"
                if re.fullmatch(r"-[a-z]*f[a-z]*", t) or t.startswith("+"):
                    return "force-push is never allowed"
            refs = [t for t in rest if not t.startswith("-")]
            if any(_is_main_ref(t) or t.endswith("/main") for t in refs):
                return "push to main is never allowed (open a PR)"
            if (len(refs) <= 1 or refs[1:] == ["head"]) and _current_branch() == "main":
                return "push while on main is never allowed (open a PR)"
        elif sub not in _KNOWN_GIT and "main" in rest:
            return f"unknown git subcommand {sub!r} (an alias?) naming main"
    return None


def check_command(command: str) -> str | None:
    c = _norm_command(command)
    if _mentions_protected(c) and (
        not _READ_ONLY.search(c) or _CHAINING.search(c)
    ):
        return (
            "only a single read-only command may name a hard-protected file "
            "(propose changes in config/protected.proposed.yaml)"
        )
    git_reason = _check_git(c)
    if git_reason:
        return git_reason
    if "gh api" in c and "refs/heads/main" in c:
        return "updating main through the GitHub API is never allowed"
    if "owner-approved" in c and ("label" in c or "gh api" in c):
        return "only the owner adds the owner-approved label"
    if any(host in c for host in API_HOSTS):
        for endpoint in _blocked_endpoints():
            if endpoint in c:
                return f"request to sealed API route {endpoint} (Law 13)"
    return None


def check_edit(file_path: str) -> str | None:
    p = _norm_path(file_path)
    for protected in HARD_PROTECTED:
        if p == protected or p.endswith("/" + protected):
            return f"edit of hard-protected {protected} (use config/protected.proposed.yaml)"
    if _mentions_protected(p.rsplit("/", 1)[-1]) and "/config/" in f"/{p}":
        return "edit of a path that may resolve to a hard-protected file"
    return None


def changed_protected_files() -> list[str]:
    """Hard-protected files whose working copy differs from git HEAD."""
    changed = []
    for path in HARD_PROTECTED:
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", path],
            capture_output=True, timeout=20, check=False,
        )
        if result.returncode != 0:
            changed.append(path)
    return changed


def post_check() -> None:
    changed = changed_protected_files()
    if changed:
        json.dump(
            {
                "decision": "block",
                "reason": (
                    f"guard.py (CLAUDE.md Law 17): hard-protected file(s) {changed} no longer "
                    "match git HEAD. Stop and tell the owner; do not continue until they "
                    "have restored or committed the file themselves."
                ),
            },
            sys.stdout,
        )


def main() -> None:
    if "--post" in sys.argv:
        post_check()
        return
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
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # fail CLOSED: exit 2 blocks the tool call
        print(f"guard.py failed, blocking to be safe: {exc!r}", file=sys.stderr)
        sys.exit(2)
