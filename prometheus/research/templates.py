"""Seed templates grouped by family -- PROMPT 7. `mutations.swap_family`
needs, for whichever family it's swapping INTO, at least one valid spec
of that family to copy parameters from (its own symbol/timeframe get
overwritten by the caller's `with_updates`, so the template's own
symbol/timeframe never leak through -- see `swap_family`'s own call).
`generate.generate_baseline_grid` already IS the real, deterministic,
classic-template set (PROMPT 6's own baseline every component must
beat); this module doesn't invent a second set of templates, it just
groups the existing one by family for that one real consumer.
"""
from __future__ import annotations

from prometheus.research.generate import generate_baseline_grid
from prometheus.strategy.spec import StrategySpec

# Symbol/timeframe are placeholders only -- swap_family always overwrites
# them with the parent spec's own values before returning a child. Any
# valid symbol/timeframe pair works; BTC/USDT 1d matches every other
# baseline grid call site in this codebase (generate.py, ablation.py).
_PLACEHOLDER_SYMBOL = "BTC/USDT"
_PLACEHOLDER_TIMEFRAME = "1d"


def seed_specs_by_family() -> dict[str, list[StrategySpec]]:
    """The real baseline grid, grouped by family -- the shape
    `mutations.swap_family`'s `seed_specs_by_family` parameter expects."""
    grouped: dict[str, list[StrategySpec]] = {}
    for spec in generate_baseline_grid(_PLACEHOLDER_SYMBOL, _PLACEHOLDER_TIMEFRAME):
        grouped.setdefault(spec.family, []).append(spec)
    return grouped
