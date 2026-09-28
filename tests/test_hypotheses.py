"""Phase 3: pre-registered hypotheses.

Unit half: every family has a mechanism, Laplace priors, the one-step
near-duplicate rule. DB half: registration is idempotent and append-only,
near-duplicates and mechanism mismatches are recorded at registration, and
the discovery gate refuses unregistered / near-duplicate / mismatched
candidates WITHOUT spending alpha-wealth while a clean registered candidate
still gets its LORD++ test."""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.experiments.runner import _apply_discovery_gate
from prometheus.research.generate import generate_baseline_grid
from prometheus.research.hypotheses import (
    is_one_step_neighbour,
    laplace_prior,
    near_duplicate_among,
    register_hypothesis,
)
from prometheus.strategy.mechanisms import MECHANISM_CLASS, mechanism_class
from prometheus.strategy.rotation_spec import ROTATION_FAMILIES
from prometheus.strategy.spec import FAMILIES, StrategySpec
from prometheus.validation.decision import DecisionResult, Verdict
from prometheus.validation.discovery_gate import ExcessReturnPValue, existing_gate_test


def test_every_family_has_a_mechanism_class() -> None:
    missing = [f for f in (*FAMILIES, *ROTATION_FAMILIES) if f not in MECHANISM_CLASS]
    assert not missing
    with pytest.raises(ValueError, match="no mechanism class"):
        mechanism_class("NOT_A_FAMILY")


def test_laplace_prior() -> None:
    assert laplace_prior(0, 0) == 0.5
    assert laplace_prior(70, 0) == 1 / 72
    assert laplace_prior(10, 3) == 4 / 12


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ({"n": 14}, {"n": 15}, True),
        ({"n": 14}, {"n": 13}, True),
        ({"n": 14}, {"n": 16}, False),
        ({"x": 2.0}, {"x": 2.1}, True),  # 0.1 <= 5% of 2.1
        ({"x": 2.0}, {"x": 2.2}, False),
        ({"n": 14, "x": 2.0}, {"n": 15, "x": 2.1}, True),
        ({"n": 14, "x": 2.0}, {"n": 15, "x": 2.5}, False),
        ({"n": 14}, {"n": 14}, False),  # identical is the same spec, not a neighbour
        ({"n": 14}, {"m": 15}, False),
        ({"flag": True, "n": 1}, {"flag": False, "n": 1}, False),
    ],
)
def test_one_step_neighbour(a: dict[str, object], b: dict[str, object], expected: bool) -> None:
    assert is_one_step_neighbour(a, b) is expected
    assert is_one_step_neighbour(b, a) is expected


def test_baseline_grid_near_duplicates_are_only_its_one_step_families() -> None:
    """The grids step by more than one, except CONSECUTIVE_DOWN (2, 3, 4):
    its later members are genuine one-step neighbours of the first."""
    grid = generate_baseline_grid("BTC/USDT", "1d")
    flagged = {
        spec.family for i, spec in enumerate(grid) if near_duplicate_among(spec, grid[:i])
    }
    assert flagged == {"CONSECUTIVE_DOWN"}


# ---------------------------------------------------------------- DB half

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"
)


def _spec(symbol: str, fast: int = 10, slow: int = 50, source: str = "mutation") -> StrategySpec:
    return StrategySpec(
        family="MOMENTUM", symbol=symbol, timeframe="1d",
        fast_window=fast, slow_window=slow, expected_horizon=5, source=source,
    )


def _symbol() -> str:
    return f"H{uuid.uuid4().hex[:10]}/USDT"


_PROMOTE = DecisionResult(Verdict.PROMOTE, 1.0, [])
_RESULT = SimpleNamespace(equity_curve=None, benchmark=SimpleNamespace(equity_curve=None))


@pytestmark_db
@pytest.mark.db
async def test_registration_is_idempotent_and_first_is_final(db_session: AsyncSession) -> None:
    spec = _spec(_symbol())
    first = await register_hypothesis(db_session, spec, stated_prior=0.3)
    again = await register_hypothesis(db_session, spec, stated_prior=0.9)
    assert first.created and not again.created
    assert again.hypothesis_id == first.hypothesis_id
    assert again.prior_probability == 0.3


@pytestmark_db
@pytest.mark.db
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE hypotheses SET prior_probability = 0.5",
        "DELETE FROM hypotheses",
        "TRUNCATE hypotheses",
    ],
)
async def test_hypotheses_are_append_only(db_session: AsyncSession, statement: str) -> None:
    await register_hypothesis(db_session, _spec(_symbol()))
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


@pytestmark_db
@pytest.mark.db
async def test_priors_mechanism_and_near_duplicates_recorded(db_session: AsyncSession) -> None:
    symbol = _symbol()
    base = await register_hypothesis(db_session, _spec(symbol, 10, 50))
    stats = (
        await db_session.execute(
            text("SELECT tests, discoveries FROM hypothesis_gate_stats WHERE source = 'mutation'")
        )
    ).one()
    assert base.near_duplicate_of is None
    assert base.prior_probability == pytest.approx(laplace_prior(stats.tests, stats.discoveries))

    neighbour = await register_hypothesis(db_session, _spec(symbol, 11, 51))
    assert neighbour.near_duplicate_of == _spec(symbol, 10, 50).config_hash()
    elsewhere = await register_hypothesis(db_session, _spec(_symbol(), 11, 51))
    assert elsewhere.near_duplicate_of is None
    far = await register_hypothesis(db_session, _spec(symbol, 20, 100))
    assert far.near_duplicate_of is None

    llm = _spec(symbol, 5, 200, source="llm_hypothesis")
    await register_hypothesis(
        db_session, llm, stated_prior=0.07, mechanism_family="RSI", claim_ids=[1]
    )
    row = (
        await db_session.execute(
            text(
                "SELECT prior_probability, prior_basis, mechanism_aligned, mechanism_class "
                "FROM hypotheses WHERE config_hash = :h"
            ),
            {"h": llm.config_hash()},
        )
    ).one()
    assert (row.prior_probability, row.prior_basis) == (0.07, "llm_stated")
    assert row.mechanism_class == "trend" and row.mechanism_aligned is False


async def _gate(session: AsyncSession, spec: StrategySpec) -> tuple[DecisionResult, dict]:
    passing = ExcessReturnPValue(p_value=1e-12, n_observations=250, sharpe_per_period=0.3)
    with patch("prometheus.experiments.runner.excess_return_pvalue", return_value=passing):
        decision, payload = await _apply_discovery_gate(
            session, spec=spec, result=_RESULT, decision=_PROMOTE, cluster_info=None
        )
    assert payload is not None
    return decision, payload


@pytestmark_db
@pytest.mark.db
@pytest.mark.usefixtures("search_unfrozen")
async def test_gate_refuses_without_spending_wealth(db_session: AsyncSession) -> None:
    symbol = _symbol()
    unregistered = _spec(symbol, 7, 30)
    near = _spec(symbol, 11, 50)
    mismatched = _spec(symbol, 5, 200, source="llm_hypothesis")
    await register_hypothesis(db_session, _spec(symbol, 10, 50))
    await register_hypothesis(db_session, near)
    await register_hypothesis(db_session, mismatched, stated_prior=0.1, mechanism_family="RSI")

    for spec, reason in [
        (unregistered, "NOT_PREREGISTERED"),
        (near, "NEAR_DUPLICATE"),
        (mismatched, "MECHANISM_MISMATCH"),
    ]:
        decision, payload = await _gate(db_session, spec)
        assert decision.verdict is Verdict.PROMISING
        assert reason in decision.reason_codes
        assert payload["tested"] is False
        assert await existing_gate_test(db_session, spec.config_hash()) is None


@pytestmark_db
@pytest.mark.db
@pytest.mark.usefixtures("search_unfrozen")
async def test_clean_registered_candidate_is_tested(db_session: AsyncSession) -> None:
    spec = _spec(_symbol(), 10, 50)
    registration = await register_hypothesis(db_session, spec)
    decision, payload = await _gate(db_session, spec)
    assert payload["tested"] is True
    assert payload["hypothesis_id"] == registration.hypothesis_id
    assert payload["prior_probability"] == registration.prior_probability
    assert await existing_gate_test(db_session, spec.config_hash()) is not None
    assert decision.verdict in (Verdict.PROMOTE, Verdict.PROMISING)


_needs_research_role = pytest.mark.skipif(
    not os.environ.get("RESEARCH_DATABASE_URL"), reason="requires RESEARCH_DATABASE_URL"
)


def _research_engine():  # type: ignore[no-untyped-def]
    return create_engine(
        os.environ["RESEARCH_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    )


@_needs_research_role
@pytest.mark.db
def test_research_role_can_register_and_read_but_not_rewrite() -> None:
    engine = _research_engine()
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            conn.execute(
                text(
                    "INSERT INTO hypotheses (config_hash, source, family, symbol, timeframe, "
                    "mechanism, mechanism_class, predicted_direction, predicted_horizon, "
                    "parameters, benchmark, prior_probability, prior_basis, mechanism_aligned) "
                    "VALUES (:h, 'llm_hypothesis', 'MOMENTUM', 'X', '1d', 'm', 'trend', "
                    "'BEATS_MATCHED_BENCHMARK', 5, '{}', '{}', 0.1, 'llm_stated', true)"
                ),
                {"h": uuid.uuid4().hex},
            )
            conn.execute(text("SELECT count(*) FROM hypothesis_gate_stats")).scalar_one()
            transaction.rollback()
        with (
            pytest.raises((DBAPIError, ProgrammingError), match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(text("UPDATE hypotheses SET prior_probability = 0.5"))
    finally:
        engine.dispose()
