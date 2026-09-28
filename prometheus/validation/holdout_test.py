"""The one-shot vault test (Law 3, user decisions 2026-09-28).

A gate discovery becomes VALIDATED only by beating its matched buy-and-hold
on bars it has never seen: every bar at or after holdout_start. The
strategy is run on research bars (its warm-up) followed by the vault bars;
only the vault part of both equity curves is scored, with the same
one-sided excess-return test the discovery gate uses, at p < 0.05. The
test runs once per spec, ever (access_holdout refuses a second read), and
only from config/holdout.yaml's vault_opens date -- six months of unseen
data. The verdict is appended to evaluator.holdout_verdicts.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.costs import load_cost_config, make_cost_model
from prometheus.backtest.engine import run_backtest
from prometheus.backtest.portfolio_engine import run_portfolio_backtest
from prometheus.data.loaders import load_point_in_time
from prometheus.data.universe import membership_windows
from prometheus.strategy.rotation_spec import RotationSpec
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.discovery_gate import excess_return_pvalue
from prometheus.validation.holdout import access_holdout, load_holdout_config

# The conventional confirmatory level, equal to the discovery gate's alpha
# (user decision 2026-09-28).
HOLDOUT_P_VALUE = 0.05


@dataclass(frozen=True)
class HoldoutVerdict:
    config_hash: str
    window_start: date | None
    window_end: date | None
    n_observations: int
    p_value: float | None
    excess_return_pct: float | None
    passed: bool


def vault_is_open(today: date | None = None) -> bool:
    config, _ = load_holdout_config()
    return (today or datetime.now(UTC).date()) >= config.vault_opens


def _day(stamp: object) -> date:
    if isinstance(stamp, datetime):
        return stamp.date()
    if isinstance(stamp, date):
        return stamp
    return date.fromisoformat(str(stamp)[:10])


def vault_slice(
    curve: Sequence[tuple[object, float]], holdout_start: date
) -> list[tuple[date, float]]:
    """The curve from the last point BEFORE holdout_start onward: that point
    is the base the first vault-day return is measured from, so every
    return scored is earned on vault bars and none on research bars."""
    points = [(_day(stamp), float(equity)) for stamp, equity in curve]
    before = [p for p in points if p[0] < holdout_start]
    after = [p for p in points if p[0] >= holdout_start]
    return ([before[-1]] if before else []) + after


def _excess_return_pct(
    strategy: list[tuple[date, float]], benchmark: list[tuple[date, float]]
) -> float | None:
    if len(strategy) < 2 or len(benchmark) < 2:
        return None
    return (
        (strategy[-1][1] / strategy[0][1] - 1) - (benchmark[-1][1] / benchmark[0][1] - 1)
    ) * 100


_INSERT_VERDICT = text(
    """
    INSERT INTO evaluator.holdout_verdicts
        (config_hash, strategy_id, window_start, window_end, n_observations, p_value,
         excess_return_pct, passed)
    VALUES
        (:config_hash, :strategy_id, :window_start, :window_end, :n_observations, :p_value,
         :excess_return_pct, :passed)
    """
)
_SELECT_PASSED_FOR_STRATEGY = text(
    """
    SELECT 1 FROM evaluator.holdout_verdicts
     WHERE passed AND config_hash = (
           SELECT config_hash FROM experiments
            WHERE strategy_id = :strategy_id ORDER BY created_at DESC LIMIT 1
     )
    """
)


_SELECT_PASSED_FOR_HASH = text(
    "SELECT 1 FROM evaluator.holdout_verdicts WHERE passed AND config_hash = :h"
)


async def holdout_passed_for_spec(session: AsyncSession, config_hash: str) -> bool:
    return (await session.execute(_SELECT_PASSED_FOR_HASH, {"h": config_hash})).first() is not None


async def holdout_passed(session: AsyncSession, strategy_id: str) -> bool:
    return (
        await session.execute(_SELECT_PASSED_FOR_STRATEGY, {"strategy_id": strategy_id})
    ).first() is not None


async def run_holdout_test(
    session: AsyncSession,
    *,
    strategy_id: str,
    spec: StrategySpec | RotationSpec,
    experiment_id: str | None,
    warmup_days: int,
    now: datetime | None = None,
) -> HoldoutVerdict:
    """Spends the spec's single vault access and records its verdict.
    Raises HoldoutAccessDenied (from access_holdout) on a second attempt.
    Does not commit."""
    config, _ = load_holdout_config()
    cutoff = now or datetime.now(UTC)
    vault = await access_holdout(session, spec, experiment_id)

    symbols = [spec.symbol] if isinstance(spec, StrategySpec) else list(spec.universe)
    holdout_start = datetime.combine(config.holdout_start, datetime.min.time(), UTC)
    research, _ = await load_point_in_time(
        session, symbols, spec.timeframe, holdout_start - timedelta(days=warmup_days), cutoff
    )
    pit = research.combined_with(vault)
    cost_model = make_cost_model(load_cost_config()[0])
    if isinstance(spec, RotationSpec):
        membership = await membership_windows(session, "etf", list(spec.universe))
        result = run_portfolio_backtest(pit, spec, membership, cutoff, cost_model=cost_model)
    else:
        result = run_backtest(pit, spec, cutoff, cost_model=cost_model)

    strategy_curve = vault_slice(result.equity_curve, config.holdout_start)
    benchmark_curve = vault_slice(result.benchmark.equity_curve, config.holdout_start)
    test = excess_return_pvalue(strategy_curve, benchmark_curve)
    verdict = HoldoutVerdict(
        config_hash=spec.config_hash(),
        window_start=strategy_curve[0][0] if strategy_curve else None,
        window_end=strategy_curve[-1][0] if strategy_curve else None,
        n_observations=test.n_observations if test else max(len(strategy_curve) - 1, 0),
        p_value=test.p_value if test else None,
        excess_return_pct=_excess_return_pct(strategy_curve, benchmark_curve),
        passed=test is not None and test.p_value < HOLDOUT_P_VALUE,
    )
    await session.execute(
        _INSERT_VERDICT,
        {
            "config_hash": verdict.config_hash,
            "strategy_id": strategy_id,
            "window_start": verdict.window_start,
            "window_end": verdict.window_end,
            "n_observations": verdict.n_observations,
            "p_value": verdict.p_value,
            "excess_return_pct": verdict.excess_return_pct,
            "passed": verdict.passed,
        },
    )
    return verdict
