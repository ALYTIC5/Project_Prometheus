"""The Claude Code PreToolUse guard (.claude/hooks/guard.py, CLAUDE.md Law 17),
run exactly as Claude Code runs it: a JSON payload on stdin, a deny decision
(or nothing) on stdout."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard.py"


def _run(tool: str, **tool_input: str) -> str | None:
    out = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    if not out.strip():
        return None
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return str(decision["permissionDecisionReason"])


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
@pytest.mark.parametrize(
    "path",
    [
        "config/protected.yaml",
        "C:\\Users\\x\\Project_Prometheus\\config\\protected.yaml",
        "/repo/config/holdout.yaml",
        "CONFIG/Protected.yaml",
    ],
)
def test_edits_of_hard_protected_files_are_denied(tool: str, path: str) -> None:
    assert _run(tool, file_path=path) is not None


def test_ordinary_edits_pass() -> None:
    assert _run("Edit", file_path="prometheus/worker.py") is None
    assert _run("Write", file_path="config/protected.proposed.yaml") is None


@pytest.mark.parametrize(
    "command",
    [
        "echo 'live_trading_enabled: true' >> config/protected.yaml",
        "sed -i 's/false/true/' config/protected.yaml",
        "Set-Content -Path config\\protected.yaml -Value x",
        "python -c \"open('config/holdout.yaml','w').write('x')\"",
        "cp /tmp/x config/holdout.yaml",
        "git checkout HEAD~3 -- config/protected.yaml",
        "git push origin main",
        "git push origin HEAD:main",
        "git push --force origin v2/p0-guardrails",
        "git push -f",
        "git push origin +v2/p0-guardrails",
        "gh pr edit 2 --add-label owner-approved",
        "gh api repos/o/r/issues/2/labels -f labels[]=owner-approved",
        "curl -s https://projectprometheus-production.up.railway.app/vault/coins",
        "Invoke-WebRequest http://localhost:8000/holdout/bars",
    ],
)
def test_dangerous_commands_are_denied(command: str) -> None:
    tool = "PowerShell" if command.startswith(("Set-Content", "Invoke")) else "Bash"
    assert _run(tool, command=command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "git diff config/protected.yaml",
        "git add config/protected.yaml",
        "git push -u origin v2/p0-guardrails",
        "curl -s https://projectprometheus-production.up.railway.app/research-health/canaries",
        ".venv/Scripts/python.exe -m pytest tests -q",
    ],
)
def test_ordinary_commands_pass(command: str) -> None:
    assert _run("Bash", command=command) is None
