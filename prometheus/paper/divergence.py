"""Materiality check for expected-vs-actual divergence (slippage, fill
behavior) -- reuses this codebase's existing z=1.96 two-tailed 95%
convention (tests/test_null_strategies.py, validation/decay.py,
experiments/ablation.py's _Z_95) rather than inventing a new percentage
threshold.

C1 (final-review fix wave): a divergence is material if the cost model's
OWN assumed slippage (config/costs.yaml's slippage_bps, loaded via
backtest.costs.load_cost_config -- never re-derived or hardcoded here) is
outside the 95% CI of the observed *adverse* slippage sample -- not if
zero is. Real market fills always show nonzero drift/slippage relative to
the last bar's close; testing against a null hypothesis of zero would
fire on nearly every champion that fills in a trend, since two
same-signed fills already push zero outside a tight CI. Testing against
the cost model's own assumption instead asks the right question: "is
this strategy's realized slippage worse than what the backtest already
assumed and charged for?"

Each reconciliation delta is normalized into "adverse_slippage_pct"
before the test: a buy order's price_delta_pct is adverse as-is (paying
more than expected costs the strategy money), a sell order's is negated
(receiving less than expected costs the strategy money) -- so "positive"
always means "cost more than the cost model assumed," matching how a
real slippage budget works.

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

import math
import statistics

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prometheus.backtest.costs import load_cost_config
from prometheus.core.db import Experiment, PaperFinding
from prometheus.core.ids import next_experiment_id

_Z_95 = 1.96

_QUARANTINE_STRATEGY = text("UPDATE strategies SET status = 'QUARANTINED' WHERE id = :id")

_SELECT_LATEST_CONFIG_HASH = text(
    "SELECT config_hash FROM experiments WHERE strategy_id = :id ORDER BY created_at DESC LIMIT 1"
)


def _is_material(deltas_pct: list[float], *, assumed_baseline_pct: float) -> bool:
    """`assumed_baseline_pct` outside the 95% CI of the sample mean --
    same z=1.96 two-tailed convention this codebase already applies
    elsewhere, not a new invented percentage cutoff. Requires at least 2
    observations to have a variance to test (same guard
    probabilistic_sharpe_ratio uses for n_observations < 2)."""
    if len(deltas_pct) < 2:
        return False
    mean = statistics.mean(deltas_pct)
    stdev = statistics.stdev(deltas_pct)
    if stdev == 0:
        # isclose, not !=: the deltas are computed floats, and a fill at
        # exactly the modelled slippage (paper/sim_broker.py) must not read
        # as material because of the last bit of float representation.
        return not math.isclose(mean, assumed_baseline_pct, rel_tol=1e-9, abs_tol=1e-12)
    n = len(deltas_pct)
    margin = _Z_95 * stdev / (n**0.5)
    return not (mean - margin <= assumed_baseline_pct <= mean + margin)


async def check_divergence(
    session: AsyncSession,
    *,
    strategy_id: str,
    reconciliation_deltas: list[dict[str, float | str]],
) -> bool:
    cost_config, _cost_config_hash = load_cost_config()
    assumed_slippage_pct = cost_config.slippage_bps / 100.0

    adverse_slippage_pct = [
        float(d["price_delta_pct"]) if d["side"] == "buy" else -float(d["price_delta_pct"])
        for d in reconciliation_deltas
    ]
    if not _is_material(adverse_slippage_pct, assumed_baseline_pct=assumed_slippage_pct):
        return False

    mean_adverse_slippage_pct = statistics.mean(adverse_slippage_pct)
    session.add(
        PaperFinding(
            strategy_id=strategy_id,
            finding_type="PAPER_DIVERGENCE",
            detail={
                "mean_adverse_slippage_pct": mean_adverse_slippage_pct,
                "assumed_slippage_pct": assumed_slippage_pct,
                "n_observations": len(adverse_slippage_pct),
            },
        )
    )
    await session.execute(_QUARANTINE_STRATEGY, {"id": strategy_id})

    latest_config_hash = (
        await session.execute(_SELECT_LATEST_CONFIG_HASH, {"id": strategy_id})
    ).scalar_one_or_none()

    proposal_id = await next_experiment_id()
    session.add(
        Experiment(
            id=proposal_id,
            status="proposed",
            strategy_id=strategy_id,
            # C2 (final-review fix wave): copy the strategy's own most
            # recent REAL experiment's config_hash forward onto this
            # proposal row instead of leaving it NULL.
            # research/population.py's _LATEST_FINGERPRINT_CTE picks the
            # newest experiment per strategy_id (ORDER BY created_at
            # DESC) to resolve that strategy's current score. A NULL
            # config_hash here would become that "latest" row, join to
            # nothing, and -- since `experiments` is append-only (Law 6)
            # and this row can never be corrected in place -- permanently
            # null out this strategy's score in every population.py query
            # (select_for_exploitation, elect_champions's
            # _SELECT_BEST_VALIDATED_PER_FAMILY, select_for_cross_breeding),
            # making it unelectable as CHAMPION again forever. The
            # proposal is "about" the strategy's current validated
            # config, not a new one -- copy-forward is the correct value,
            # not a workaround.
            config_hash=latest_config_hash,
            hypothesis=(
                f"Observed mean adverse slippage of {mean_adverse_slippage_pct:.3f}% across "
                f"{len(adverse_slippage_pct)} paper trades diverges from the cost model's "
                f"assumed {assumed_slippage_pct:.3f}% (config/costs.yaml's slippage_bps) -- "
                "recalibrate config/costs.yaml's slippage_bps."
            ),
            change_set={
                "proposed_recalibration": "slippage_bps",
                "observed_mean_adverse_slippage_pct": mean_adverse_slippage_pct,
                "assumed_slippage_pct": assumed_slippage_pct,
            },
        )
    )
    await session.commit()
    return True
