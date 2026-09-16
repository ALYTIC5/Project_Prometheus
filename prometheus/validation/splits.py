"""Walk-forward folds with purge and embargo, over cpz-quant's own CV
splitters (CLAUDE.md: don't reimplement purged/combinatorial CV from
scratch). Operates on bar INDICES, not timestamps -- callers map fold
indices back to bar timestamps themselves (the sorted bars they already
loaded via PointInTimeFrame.as_of()), so this module stays a pure,
testable function with no DB/PointInTimeFrame dependency of its own.

Purge = embargo = the strategy's own expected_horizon, not an invented
gap size: the window must cover exactly how far a decision's outcome is
claimed to extend before a test fold can be trusted not to still be
resolving a training-fold event. A shorter gap risks leakage from a
still-resolving signal; a longer one only wastes data with no leakage
argument requiring it.
"""
from __future__ import annotations

from dataclasses import dataclass

from cpz_quant.portfolio.model_selection import CombinatorialPurgedCV, WalkForward

# CombinatorialPurgedCV needs >= n_splits * 2 observations (its own
# ValueError). Below that there still isn't enough history for a
# meaningful combinatorial fold count, so a plain expanding WalkForward
# with 2 folds is the smallest walk-forward split that still has a
# genuinely held-out final window -- not an invented number, the floor a
# walk-forward split needs by definition (>=1 train fold, >=1 test fold).
_MIN_WALK_FORWARD_SPLITS = 2
_CPCV_N_SPLITS = 6
_CPCV_N_TEST_SPLITS = 2


@dataclass(frozen=True)
class Fold:
    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]


def _walk_forward_folds(n_bars: int) -> list[Fold]:
    wf = WalkForward(n_splits=_MIN_WALK_FORWARD_SPLITS, expanding=True)
    folds = [Fold(tuple(tr), tuple(te)) for tr, te in wf.split(n_bars)]
    if not folds:
        raise ValueError(f"not enough bars ({n_bars}) to derive any walk-forward fold")
    return folds


def derive_folds(n_bars: int, expected_horizon: int) -> list[Fold]:
    """Combinatorial purged folds when there's enough history for
    cpz-quant's default 6-split/2-test-split CPCV shape (C(6,2)=15 folds)
    with the purge/embargo gap subtracted; otherwise a 2-fold expanding
    WalkForward, so a strategy with a short backtest window still gets a
    real held-out test fold instead of an exception the caller has to
    special-case.

    The n_bars floor below is a necessary-but-not-sufficient pre-check
    (n_test_splits=2 means a fold's purge/embargo halos surround TWO
    groups, and depending which two are chosen combinatorially, those
    halos can still overlap and block most of a series even when the
    simple floor is satisfied -- caught by actually running this against
    real bar counts, not derived analytically). cpz-quant's own
    CombinatorialPurgedCV.split() is the authority on whether a given
    combination is actually viable; when it isn't, this falls back to
    WalkForward rather than letting one pathological combination take
    down the whole caller.
    """
    if n_bars <= 0:
        raise ValueError("n_bars must be positive")
    if expected_horizon <= 0:
        raise ValueError("expected_horizon must be positive")

    min_bars_for_cpcv = _CPCV_N_SPLITS * 2 + 2 * expected_horizon
    if n_bars >= min_bars_for_cpcv:
        cv = CombinatorialPurgedCV(
            n_splits=_CPCV_N_SPLITS,
            n_test_splits=_CPCV_N_TEST_SPLITS,
            purge=expected_horizon,
            embargo=expected_horizon,
        )
        try:
            return [Fold(tuple(tr), tuple(te)) for tr, te in cv.split(n_bars)]
        except ValueError:
            pass  # this horizon/n_bars combination isn't viable for CPCV

    return _walk_forward_folds(n_bars)
