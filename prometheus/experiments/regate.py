"""One-time re-test of promotions made before the discovery gate existed
(user decision 2026-09-28).

Every CHAMPION and VALIDATED strategy was promoted by the old
`deflated_sharpe > 0` check, which was always true. Each now faces its one
LORD++ test (an earlier test of the same spec is reused, never repeated),
on research bars only. Nobody keeps CHAMPION/VALIDATED -- nobody has passed
the vault test, which is now required (validation/status.py) -- so every
one goes to PROMISING: discoveries are then paper-traded as "awaiting
holdout" (validation/promotion.paper_eligible_strategies), the rest stop
trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.costs import load_cost_config, make_cost_model
from prometheus.backtest.engine import run_backtest
from prometheus.backtest.portfolio_engine import run_portfolio_backtest
from prometheus.data.loaders import load_point_in_time
from prometheus.data.universe import membership_windows
from prometheus.strategy.rotation_spec import ROTATION_FAMILIES, RotationSpec
from prometheus.strategy.spec import StrategySpec
from prometheus.validation.discovery_gate import (
    GateTest,
    excess_return_pvalue,
    existing_gate_test,
    run_gate_test,
)
from prometheus.validation.status import note_discovery, set_status

_SELECT_PRE_GATE_PROMOTED = text(
    "SELECT id, family, spec FROM strategies WHERE status IN ('CHAMPION', 'VALIDATED') ORDER BY id"
)


@dataclass
class RegateReport:
    discoveries: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    untestable: list[str] = field(default_factory=list)


async def _gate_test_for(
    session: AsyncSession, spec: StrategySpec | RotationSpec, *, lookback_days: int, now: datetime
) -> GateTest | None:
    earlier = await existing_gate_test(session, spec.config_hash())
    if earlier is not None:
        return earlier
    symbols = [spec.symbol] if isinstance(spec, StrategySpec) else list(spec.universe)
    pit, _ = await load_point_in_time(
        session, symbols, spec.timeframe, now - timedelta(days=lookback_days), now
    )
    cost_model = make_cost_model(load_cost_config()[0])
    if isinstance(spec, RotationSpec):
        membership = await membership_windows(session, "etf", list(spec.universe))
        result = run_portfolio_backtest(pit, spec, membership, now, cost_model=cost_model)
    else:
        result = run_backtest(pit, spec, now, cost_model=cost_model)
    pvalue = excess_return_pvalue(result.equity_curve, result.benchmark.equity_curve)
    if pvalue is None:
        return None
    return await run_gate_test(session, spec.config_hash(), pvalue)


async def regate_pre_gate_promotions(
    session: AsyncSession, *, lookback_days: int, now: datetime | None = None
) -> RegateReport:
    """Does not commit."""
    cutoff = now or datetime.now(UTC)
    report = RegateReport()
    rows = (await session.execute(_SELECT_PRE_GATE_PROMOTED)).fetchall()
    for row in rows:
        try:
            spec: StrategySpec | RotationSpec = (
                RotationSpec.model_validate(row.spec)
                if row.family in ROTATION_FAMILIES
                else StrategySpec.model_validate(row.spec)
            )
            test = await _gate_test_for(session, spec, lookback_days=lookback_days, now=cutoff)
        except ValueError:  # an unparseable spec, or too few research bars to backtest
            test = None
        if test is None:
            report.untestable.append(row.id)
            reason = "pre-gate promotion re-tested: too little data for the discovery gate"
        elif test.discovery:
            report.discoveries.append(row.id)
            reason = "pre-gate promotion re-tested: discovery, awaiting holdout"
        else:
            report.failed.append(row.id)
            reason = "pre-gate promotion re-tested: failed the discovery gate"
        await set_status(session, row.id, "PROMISING", reason=reason)
        if test is not None and test.discovery:
            await note_discovery(session, row.id, reason=reason)
    return report
