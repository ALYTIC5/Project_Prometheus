"""Ordinary correctness coverage for the YAML-loading half of
`prometheus.core.config` — the `ResearchPolicy` model, the content hash,
and `load_research_policy`.

Deliberately NOT under `tests/laws/`. None of the seven laws is at stake
here; the policy/risk separation that *is* a law is tested by
`tests/laws/test_policy_cannot_reach_risk.py`. What is checked here is
that the policy still ships with no invented numeric thresholds, that the
hash is a real content hash, and that no call shape of
`load_research_policy` can skip writing its version row.

No database is needed: the session is a fake with the two methods the
function actually uses.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from prometheus.core.config import (
    DEFAULT_RESEARCH_POLICY_PATH,
    ResearchPolicy,
    _content_hash,
    load_research_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / DEFAULT_RESEARCH_POLICY_PATH


def _fake_session() -> MagicMock:
    """A stand-in for AsyncSession exposing only `.add()` and `.flush()`."""
    session = MagicMock()
    session.flush = AsyncMock()
    return session


def test_ships_with_no_numeric_thresholds() -> None:
    # CLAUDE.md: inventing numeric thresholds is how the previous blueprint
    # went wrong. schema_version is bookkeeping, not a threshold.
    assert set(ResearchPolicy.model_fields) == {"schema_version"}


def test_parses_the_repo_policy_file() -> None:
    data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    policy = ResearchPolicy(**data)
    assert policy.schema_version == data["schema_version"]


def test_content_hash_is_deterministic() -> None:
    raw = "schema_version: 1\n"
    assert _content_hash(raw) == _content_hash(raw)


def test_content_hash_is_sensitive_to_content() -> None:
    assert _content_hash("schema_version: 1\n") != _content_hash("schema_version: 2\n")


def test_content_hash_is_sha256_hex() -> None:
    digest = _content_hash("schema_version: 1\n")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


async def test_load_writes_a_policy_version_row() -> None:
    from prometheus.core.db import PolicyVersion

    session = _fake_session()
    policy = await load_research_policy(session, path=POLICY_PATH)

    assert isinstance(policy, ResearchPolicy)
    session.add.assert_called_once()
    (row,) = session.add.call_args.args
    assert isinstance(row, PolicyVersion)
    raw = POLICY_PATH.read_text(encoding="utf-8")
    assert row.raw_yaml == raw
    assert row.content_hash == _content_hash(raw)


async def test_load_flushes_but_does_not_commit() -> None:
    # Flushing orders the row inside the caller's transaction; committing
    # the caller's transaction is not this helper's decision to make.
    session = _fake_session()
    await load_research_policy(session, path=POLICY_PATH)
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


async def test_load_versions_every_call() -> None:
    session = _fake_session()
    await load_research_policy(session, path=POLICY_PATH)
    await load_research_policy(session, path=POLICY_PATH)
    assert session.add.call_count == 2
    assert session.flush.await_count == 2


async def test_load_reads_the_given_path(tmp_path: Path) -> None:
    custom = tmp_path / "policy.yaml"
    custom.write_text("schema_version: 7\n", encoding="utf-8")
    session = _fake_session()
    policy = await load_research_policy(session, path=custom)
    assert policy.schema_version == 7
    (row,) = session.add.call_args.args
    assert row.content_hash == _content_hash("schema_version: 7\n")


async def test_load_requires_a_session() -> None:
    # The session is positional-and-required: there is no call shape that
    # loads a policy without writing its version row.
    with pytest.raises(TypeError):
        await load_research_policy()  # type: ignore[call-arg]
