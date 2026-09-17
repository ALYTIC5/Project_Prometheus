"""Materiality check for expected-vs-actual divergence (slippage, fill
behavior) -- reuses this codebase's existing z=1.96 two-tailed 95%
convention (tests/test_null_strategies.py, validation/decay.py,
experiments/ablation.py's _Z_95) rather than inventing a new percentage
threshold: a divergence is material if zero is outside the 95% CI of the
observed price_delta_pct sample, not merely if the mean is nonzero.

On a material divergence: writes PAPER_DIVERGENCE, quarantines the
strategy (population.py's existing QUARANTINED status -- no new state),
and records the recalibration proposal as a new `experiments` row
(status="proposed"), never a queue job -- experiments/runner.py::run_one
raises ValueError for any job kind other than "run_backtest", and
PROMPTS.md's own wording is "propose... as a new experiment" anyway.
Nothing acts on this proposal automatically: Law 7 requires a threshold
change to be re-evaluated across the entire historical corpus, never
adopted from one strategy's proposal.
"""
from __future__ import annotations

import statistics

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.core.db import Experiment, PaperFinding
from prometheus.core.ids import next_experiment_id

_Z_95 = 1.96

_QUARANTINE_STRATEGY = text("UPDATE strategies SET status = 'QUARANTINED' WHERE id = :id")


def _is_material(deltas_pct: list[float]) -> bool:
    """Zero outside the 95% CI of the sample mean -- same z=1.96
    two-tailed convention this codebase already applies elsewhere, not a
    new invented percentage cutoff. Requires at least 2 observations to
    have a variance to test (same guard probabilistic_sharpe_ratio uses
    for n_observations < 2)."""
    if len(deltas_pct) < 2:
        return False
    mean = statistics.mean(deltas_pct)
    stdev = statistics.stdev(deltas_pct)
    if stdev == 0:
        return mean != 0
    n = len(deltas_pct)
    margin = _Z_95 * stdev / (n**0.5)
    return not (mean - margin <= 0 <= mean + margin)


async def check_divergence(
    session: AsyncSession,
    *,
    strategy_id: str,
    reconciliation_deltas: list[dict[str, float]],
) -> bool:
    price_deltas = [d["price_delta_pct"] for d in reconciliation_deltas]
    if not _is_material(price_deltas):
        return False

    mean_delta = statistics.mean(price_deltas)
    session.add(
        PaperFinding(
            strategy_id=strategy_id,
            finding_type="PAPER_DIVERGENCE",
            detail={"mean_price_delta_pct": mean_delta, "n_observations": len(price_deltas)},
        )
    )
    await session.execute(_QUARANTINE_STRATEGY, {"id": strategy_id})

    proposal_id = await next_experiment_id()
    session.add(
        Experiment(
            id=proposal_id,
            status="proposed",
            strategy_id=strategy_id,
            hypothesis=(
                f"Observed mean fill-price divergence of {mean_delta:.3f}% across "
                f"{len(price_deltas)} paper trades exceeds the cost model's implicit "
                "slippage assumption -- recalibrate config/costs.yaml's slippage_bps."
            ),
            change_set={"proposed_recalibration": "slippage_bps", "observed_mean_delta_pct": mean_delta},
        )
    )
    await session.commit()
    return True
