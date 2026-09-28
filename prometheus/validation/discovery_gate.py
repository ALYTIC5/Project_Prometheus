"""prometheus/validation/discovery_gate.py -- the online-FDR discovery gate
(Law 10: every discovery spends alpha-wealth; no path to VALIDATED
bypasses it).

LORD++, from Ramdas, Yang, Wainwright & Jordan (2017), "Online control of
the false discovery rate with decaying memory" (NeurIPS): the t-th test
rejects its null (a DISCOVERY) iff p_t <= alpha_t, where

    alpha_t = gamma_t*W0 + (alpha - W0)*gamma_{t - tau_1}
              + alpha * sum_{j >= 2} gamma_{t - tau_j}

tau_j are the indices of earlier discoveries and gamma is the paper's
default non-increasing sequence summing to ~1. It controls FDR at alpha for
an unbounded stream of tests under independence (and a local form of
positive dependence) -- backtests on shared data are dependent in other
ways too, so control here is approximate; tests/test_discovery_gate.py
measures how far it degrades under correlation instead of claiming it.

Parameters (user decision 2026-09-28): alpha = 5%, W0 = alpha / 2 (the
paper's default initial wealth).

The p-value (docs/DECISIONS.md): Probabilistic Sharpe Ratio of the
strategy's per-bar EXCESS returns over its own matched buy-and-hold (Law 8)
against zero, per-period units. Not the Deflated Sharpe -- that already
corrects for the number of trials and would double-correct.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from itertools import pairwise

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.validation.multiple_testing import probabilistic_sharpe_ratio

ALPHA = 0.05
W0 = ALPHA / 2
_GAMMA_CONSTANT = 0.0722  # normalises the paper's default sequence to ~1
# cpz-quant's own floor for risk analytics (30 equity points), already this
# codebase's convention for "enough observations to estimate a Sharpe".
MIN_OBSERVATIONS = 30


@cache
def gamma(j: int) -> float:
    if j < 1:
        raise ValueError(f"gamma is defined for j >= 1, got {j}")
    return _GAMMA_CONSTANT * math.log(max(j, 2)) / (j * math.exp(math.sqrt(math.log(j))))


def lord_threshold(
    t: int, discovery_indices: Sequence[int], *, alpha: float = ALPHA, w0: float = W0
) -> float:
    """alpha_t for the t-th test (1-based), given the indices (< t) of
    every earlier discovery in order."""
    earlier = [tau for tau in discovery_indices if tau < t]
    threshold = gamma(t) * w0
    if earlier:
        threshold += (alpha - w0) * gamma(t - earlier[0])
        threshold += alpha * sum(gamma(t - tau) for tau in earlier[1:])
    return threshold


def wealth(
    thresholds_spent: Sequence[float], n_discoveries: int, *, alpha: float = ALPHA, w0: float = W0
) -> float:
    """Remaining alpha-wealth in the GAI++ accounting LORD++ satisfies:
    initial wealth, minus every threshold spent, plus (alpha - W0) for the
    first discovery and alpha for each one after."""
    earned = (alpha - w0) * (n_discoveries >= 1) + alpha * max(n_discoveries - 1, 0)
    return w0 - sum(thresholds_spent) + earned


@dataclass(frozen=True)
class ExcessReturnPValue:
    p_value: float
    n_observations: int
    sharpe_per_period: float


def _by_date(curve: Sequence[tuple[object, float]]) -> dict[date, float]:
    """Last equity value per calendar date. Strategy curves carry ISO
    strings, benchmark curves carry dates."""
    out: dict[date, float] = {}
    for stamp, equity in curve:
        if isinstance(stamp, datetime):
            day = stamp.date()
        elif isinstance(stamp, date):
            day = stamp
        else:
            day = date.fromisoformat(str(stamp)[:10])
        out[day] = float(equity)
    return out


def excess_return_pvalue(
    strategy_curve: Sequence[tuple[object, float]],
    benchmark_curve: Sequence[tuple[object, float]],
) -> ExcessReturnPValue | None:
    """One-sided p-value that the strategy's excess return over its matched
    buy-and-hold has a Sharpe <= 0. None when there are too few shared
    observations or the excess series is degenerate."""
    strategy = _by_date(strategy_curve)
    benchmark = _by_date(benchmark_curve)
    days = sorted(set(strategy) & set(benchmark))
    excess = []
    for previous, current in pairwise(days):
        if strategy[previous] <= 0 or benchmark[previous] <= 0:
            return None
        r_strategy = strategy[current] / strategy[previous] - 1
        r_benchmark = benchmark[current] / benchmark[previous] - 1
        excess.append(r_strategy - r_benchmark)
    n = len(excess)
    if n < MIN_OBSERVATIONS:
        return None
    mean = sum(excess) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in excess) / (n - 1))
    if sd == 0:
        return None
    sharpe = mean / sd
    skew = sum((x - mean) ** 3 for x in excess) / n / sd**3
    kurtosis = sum((x - mean) ** 4 for x in excess) / n / sd**4
    psr = probabilistic_sharpe_ratio(sharpe, 0.0, n, skew, kurtosis)
    if psr is None:
        return None
    return ExcessReturnPValue(p_value=1.0 - psr, n_observations=n, sharpe_per_period=sharpe)


@dataclass(frozen=True)
class GateTest:
    test_index: int
    p_value: float
    alpha_threshold: float
    discovery: bool
    wealth_before: float
    wealth_after: float
    reused: bool


_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('alpha_wealth_ledger'))")
_SELECT_EXISTING = text(
    """
    SELECT test_index, p_value, alpha_threshold, discovery, wealth_before, wealth_after
      FROM evaluator.alpha_wealth_ledger WHERE config_hash = :h
    """
)
_SELECT_HISTORY = text(
    "SELECT test_index, alpha_threshold, discovery "
    "FROM evaluator.alpha_wealth_ledger ORDER BY test_index"
)
_INSERT = text(
    """
    INSERT INTO evaluator.alpha_wealth_ledger
        (test_index, config_hash, p_value, alpha_threshold, discovery,
         wealth_before, wealth_after, n_observations, excess_sharpe_per_period)
    VALUES (:test_index, :config_hash, :p_value, :alpha_threshold, :discovery,
            :wealth_before, :wealth_after, :n_observations, :sharpe)
    """
)
_SELECT_DISCOVERY_FOR_STRATEGY = text(
    """
    SELECT 1 FROM evaluator.alpha_wealth_ledger
     WHERE discovery AND config_hash = (
           SELECT config_hash FROM experiments
            WHERE strategy_id = :strategy_id ORDER BY created_at DESC LIMIT 1
     )
    """
)


async def existing_gate_test(session: AsyncSession, config_hash: str) -> GateTest | None:
    row = (await session.execute(_SELECT_EXISTING, {"h": config_hash})).first()
    if row is None:
        return None
    return GateTest(
        test_index=row.test_index, p_value=row.p_value, alpha_threshold=row.alpha_threshold,
        discovery=row.discovery, wealth_before=row.wealth_before,
        wealth_after=row.wealth_after, reused=True,
    )


async def run_gate_test(
    session: AsyncSession, config_hash: str, pvalue: ExcessReturnPValue
) -> GateTest:
    """One LORD++ test per config_hash, ever: a spec already in the ledger
    gets its recorded outcome back and spends nothing. Serialised with a
    transaction-scoped advisory lock so test indices are never shared.
    Does not commit."""
    await session.execute(_LOCK)
    existing = await existing_gate_test(session, config_hash)
    if existing is not None:
        return existing
    history = (await session.execute(_SELECT_HISTORY)).all()
    t = len(history) + 1
    discoveries = [row.test_index for row in history if row.discovery]
    spent = [row.alpha_threshold for row in history]
    threshold = lord_threshold(t, discoveries)
    discovery = pvalue.p_value <= threshold
    before = wealth(spent, len(discoveries))
    after = wealth([*spent, threshold], len(discoveries) + int(discovery))
    await session.execute(
        _INSERT,
        {
            "test_index": t, "config_hash": config_hash, "p_value": pvalue.p_value,
            "alpha_threshold": threshold, "discovery": discovery,
            "wealth_before": before, "wealth_after": after,
            "n_observations": pvalue.n_observations, "sharpe": pvalue.sharpe_per_period,
        },
    )
    return GateTest(t, pvalue.p_value, threshold, discovery, before, after, reused=False)


async def has_discovery(session: AsyncSession, strategy_id: str) -> bool:
    return (
        await session.execute(_SELECT_DISCOVERY_FOR_STRATEGY, {"strategy_id": strategy_id})
    ).first() is not None
