"""The CI guard against the automated loop changing the evaluator, run
against a real throwaway git repository."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.ci.check_protected_paths import (
    LOOP_AUTHOR_EMAIL,
    OWNER_APPROVAL_LABEL,
    POLICY_BRANCH,
    find_offences,
    is_protected,
    main,
    needs_owner_approval,
    unapproved_changes,
)


def _git(repo: Path, *args: str, email: str = "human@example.com") -> str:
    return subprocess.run(
        ["git", "-c", f"user.email={email}", "-c", "user.name=t", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, path: str, *, email: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{target.read_text() if target.exists() else ''}x\n")
    _git(repo, "add", path, email=email)
    _git(repo, "commit", "-q", "-m", f"change {path}", email=email)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, str]:
    _git(tmp_path, "init", "-q", "-b", "main")
    base = _commit(tmp_path, "README.md", email="human@example.com")
    return tmp_path, base


@pytest.mark.parametrize(
    "path",
    [
        "prometheus/validation/status.py",
        "prometheus/validation/canaries.py",
        "prometheus/validation/holdout.py",
        "prometheus/core/config.py",
        "config/holdout.yaml",
        "alembic/versions/0024_research_role_and_evaluator_schema.py",
        "tests/laws/test_evaluator_isolation.py",
        "CLAUDE.md",
        ".github/workflows/ci.yml",
        "tools/ci/check_protected_paths.py",
    ],
)
def test_protected_paths(path: str) -> None:
    assert is_protected(path)


def test_research_code_is_not_protected() -> None:
    assert not is_protected("prometheus/research/population.py")
    assert not is_protected("config/research_policy.yaml")


def test_loop_commit_touching_validation_fails(repo: tuple[Path, str]) -> None:
    path, base = repo
    head = _commit(path, "prometheus/validation/scoring.py", email=LOOP_AUTHOR_EMAIL)
    offences = find_offences(base, head, "main", cwd=str(path))
    assert [(o.path, o.author) for o in offences] == [
        ("prometheus/validation/scoring.py", LOOP_AUTHOR_EMAIL)
    ]


def test_any_commit_on_the_policy_branch_touching_laws_fails(repo: tuple[Path, str]) -> None:
    path, base = repo
    head = _commit(path, "tests/laws/test_x.py", email="human@example.com")
    assert find_offences(base, head, POLICY_BRANCH, cwd=str(path))


def test_loop_commit_touching_only_policy_config_passes(repo: tuple[Path, str]) -> None:
    path, base = repo
    head = _commit(path, "config/research_policy.yaml", email=LOOP_AUTHOR_EMAIL)
    assert find_offences(base, head, POLICY_BRANCH, cwd=str(path)) == []


def test_human_commit_on_main_is_not_checked(repo: tuple[Path, str]) -> None:
    path, base = repo
    head = _commit(path, "prometheus/validation/scoring.py", email="human@example.com")
    assert find_offences(base, head, "main", cwd=str(path)) == []


def test_offence_anywhere_in_the_range_is_caught(repo: tuple[Path, str]) -> None:
    path, base = repo
    _commit(path, "alembic/versions/0099_new_role.py", email=LOOP_AUTHOR_EMAIL)
    head = _commit(path, "config/research_policy.yaml", email=LOOP_AUTHOR_EMAIL)
    offences = find_offences(base, head, "main", cwd=str(path))
    assert [o.path for o in offences] == ["alembic/versions/0099_new_role.py"]


# ------------------------------------------------ owner approval (Law 17)


@pytest.mark.parametrize(
    "path",
    [
        "config/protected.yaml",
        "config/holdout.yaml",
        "config/gates.yaml",
        "config/search.yaml",
        ".github/CODEOWNERS",
        ".gitleaks.toml",
        "tests/laws/test_new.py",
        ".github/workflows/ci.yml",
        ".claude/settings.json",
        ".claude/hooks/guard.py",
        "tools/ci/check_protected_paths.py",
    ],
)
def test_owner_approval_paths(path: str) -> None:
    assert needs_owner_approval(path)


def test_ordinary_code_needs_no_owner_approval() -> None:
    assert not needs_owner_approval("prometheus/worker.py")
    assert not needs_owner_approval("tests/test_worker.py")
    assert not needs_owner_approval("config/costs.yaml")


def _pr(repo: tuple[Path, str], paths: list[str]) -> tuple[str, str, str]:
    path, base = repo
    _git(path, "switch", "-q", "-c", "feature")
    head = base
    for changed in paths:
        head = _commit(path, changed, email="human@example.com")
    return str(path), base, head


def test_simulated_pr_touching_protected_config_needs_the_label(
    repo: tuple[Path, str],
) -> None:
    cwd, base, head = _pr(repo, ["config/protected.yaml", "prometheus/worker.py"])
    assert unapproved_changes(base, head, [], cwd=cwd) == ["config/protected.yaml"]
    assert unapproved_changes(base, head, ["bug"], cwd=cwd) == ["config/protected.yaml"]
    assert unapproved_changes(base, head, [OWNER_APPROVAL_LABEL], cwd=cwd) == []


def test_simulated_pr_without_protected_paths_passes_unlabelled(
    repo: tuple[Path, str],
) -> None:
    cwd, base, head = _pr(repo, ["prometheus/worker.py"])
    assert unapproved_changes(base, head, [], cwd=cwd) == []


def test_cli_fails_unlabelled_and_passes_labelled(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd, base, head = _pr(repo, [".claude/settings.json"])
    monkeypatch.chdir(cwd)
    args = ["--base", base, "--head", head, "--branch", "feature", "--pr"]
    assert main([*args, "--labels", ""]) == 1
    assert main([*args, "--labels", f"docs,{OWNER_APPROVAL_LABEL}"]) == 0
