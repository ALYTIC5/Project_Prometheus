"""The Claude Code guard hook (.claude/hooks/guard.py, CLAUDE.md Law 17),
run exactly as Claude Code runs it: a JSON payload on stdin, a decision (or
nothing) on stdout. The bypass cases are the P0 verifier's findings
(2026-09-29); each must stay blocked."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

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


def _guard() -> Any:
    spec = importlib.util.spec_from_file_location("guard", _HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
@pytest.mark.parametrize(
    "path",
    [
        "config/protected.yaml",
        "C:\\Users\\x\\Project_Prometheus\\config\\protected.yaml",
        "/repo/config/holdout.yaml",
        "CONFIG/Protected.yaml",
        "C:/repo/config/./protected.yaml",
        "C:/repo/config/protected.yaml::$DATA",
        "C:/repo/config/protected.yaml.",
        "C:/repo/config/PROTEC~1.YAM",
        "C:/repo/config/protected.yaml ",
    ],
)
def test_edits_of_hard_protected_files_are_denied(tool: str, path: str) -> None:
    assert _run(tool, file_path=path) is not None


def test_ordinary_edits_pass() -> None:
    assert _run("Edit", file_path="prometheus/worker.py") is None
    assert _run("Write", file_path="config/protected.proposed.yaml") is None


_DENIED = [
    # writes to a hard-protected file
    "echo 'live_trading_enabled: true' >> config/protected.yaml",
    "sed -i 's/false/true/' config/protected.yaml",
    "python -c \"open('config/holdout.yaml','w').write('x')\"",
    "cp /tmp/x config/holdout.yaml",
    "git checkout HEAD~3 -- config/protected.yaml",
    "echo x|tee -a config/protected.yaml",
    "true;rm config/protected.yaml",
    "true&&cp /tmp/x config/protected.yaml",
    "/bin/cp /tmp/x config/protected.yaml",
    "\\cp /tmp/x config/protected.yaml",
    "patch config/protected.yaml /tmp/p.diff",
    "rsync /tmp/x config/protected.yaml",
    "vim -c 'wq' config/protected.yaml",
    "echo x >> config/protected.yam?",
    "echo x >> config/protected.*",
    "echo x >> config/./protected.yaml",
    "echo x >> config//protected.yaml",
    "cd config && echo x >> protected.yaml",
    "d=config; echo x >> $d/protected.yaml",
    "python -c \"import shutil; shutil.copy('/tmp/x', 'config/protected.yaml')\"",
    "python -c \"import os; os.replace('/tmp/x', 'config/protected.yaml')\"",
    "[IO.File]::AppendAllText('config/protected.yaml', 'x')",
    "copy C:\\tmp\\x config/protected.yaml",
    "del config/protected.yaml",
    "sc config/protected.yaml x",
    "ac config/protected.yaml x",
    "cpi C:\\tmp\\x config/protected.yaml",
    "ri config/protected.yaml",
    "Set-Content -Path config\\protected.yaml -Value x",
    # push to main, force-push
    "git push origin main",
    "git push origin HEAD:main",
    "git push origin 'HEAD:main'",
    "git push origin \"main\"",
    "git push origin ma''in",
    "bash -c 'git push origin main'",
    "git push origin $(echo main)",
    "git push origin HEAD:refs/heads/ma\\in",
    "git p origin main",
    "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
    "git push --force origin v2/p0-guardrails",
    "git push -f",
    "git push -uf origin feature",
    "git push -fu origin feature",
    "git push origin +v2/p0-guardrails",
    # owner label, sealed routes
    "gh pr edit 2 --add-label owner-approved",
    "gh api repos/o/r/issues/2/labels -f labels[]=owner-approved",
    "curl -s https://projectprometheus-production.up.railway.app/vault/coins",
    "Invoke-WebRequest http://localhost:8000/holdout/bars",
]


@pytest.mark.parametrize("command", _DENIED)
def test_dangerous_commands_are_denied(command: str) -> None:
    assert _run("Bash", command=command) is not None


@pytest.mark.parametrize("command", ["git push origin HEAD", "git push -u origin HEAD", "git push"])
def test_pushes_while_on_main_are_denied(command: str) -> None:
    guard = _guard()
    with patch.object(guard, "_current_branch", return_value="main"):
        assert guard.check_command(command) is not None
    with patch.object(guard, "_current_branch", return_value="v2/p0-guardrails"):
        assert guard.check_command(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "git diff config/protected.yaml",
        "git show HEAD:config/holdout.yaml",
        "git add config/protected.yaml",
        "cat config/protected.yaml",
        "Get-Content config\\holdout.yaml",
        "git push -u origin v2/p0-guardrails",
        "git diff main...HEAD -- CLAUDE.md",
        "git log --oneline main",
        "git switch main",
        "curl -s https://projectprometheus-production.up.railway.app/research-health/canaries",
        ".venv/Scripts/python.exe -m pytest tests -q",
        ".venv/Scripts/python.exe -m pytest tests/test_protected_config.py -q",
    ],
)
def test_ordinary_commands_pass(command: str) -> None:
    assert _run("Bash", command=command) is None


def test_post_check_flags_a_protected_file_changed_by_any_route(tmp_path: Path) -> None:
    """The backstop for writes no PreToolUse heuristic can see (a script
    written elsewhere first): after the tool call, a protected file that no
    longer matches git HEAD blocks with an explanation."""
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )

    git("init", "-q")
    (tmp_path / "config").mkdir()
    protected = tmp_path / "config" / "protected.yaml"
    protected.write_text("live_trading_enabled: false\n")
    git("add", ".")
    git("commit", "-q", "-m", "init")

    def post() -> str:
        return subprocess.run(
            [sys.executable, str(_HOOK), "--post"], cwd=tmp_path,
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout

    assert post().strip() == ""
    protected.write_text("live_trading_enabled: true\n")
    decision = json.loads(post())
    assert decision["decision"] == "block"
    assert "config/protected.yaml" in decision["reason"]


def test_the_hook_fails_closed() -> None:
    result = subprocess.run(
        [sys.executable, str(_HOOK)], input="not json", capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 2
