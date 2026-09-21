# Strategy pre-registration

Every new strategy family added from this point forward gets a
`docs/strategies/<family>.md` written **before** its first backtest runs
-- not after, not "once it looks promising." This is Step 2 of the
"100 strategies" research prompt (`docs/strategies/STRATEGIES_100.md`,
once that batch work starts) and applies to any new family added by any
future prompt, not just that one.

## Why before, not after

Parameter ranges are fixed at registration. Widening a grid's parameter
range after seeing which values happened to backtest well is p-hacking
with extra steps, and CLAUDE.md's Law 7 already names the general
version of this failure: "Thresholds change globally or not at all... a
validation threshold may be changed only by an experiment that
re-evaluates it across the entire historical experiment corpus."
Pre-registration is the same discipline applied one level up, to the
grid itself, not just the verdict thresholds scored against it.

## What every registration doc must state

1. **Hypothesis** -- the actual economic/behavioral reason this signal
   might work, in plain language. Not "it's a classic indicator" --
   *why* would classic-indicator-shaped price action predict returns.
2. **Source** -- a citation (author, paper, or the specific named
   trading-literature convention) or an honest "no citation, this is a
   novel construction" if that's the truth. Every family this project
   has shipped so far cites a real, named construction
   (`prometheus/strategy/spec.py`'s own module docstring lists all of
   them) -- this is the existing bar, made explicit as a process step
   rather than left as an ambient convention.
3. **Parameter ranges** -- the exact grid values `research/generate.py`
   (or `research/ml/generate.py` for an ML component) will use, fixed
   here first. If a later experiment wants a different range, that is a
   new registration, not an edit to this one after the fact.
4. **Expected horizon** -- the same claim `StrategySpec.expected_horizon`
   already requires in code, stated in prose here first.
5. **Benchmark** -- which Law 8 buy-and-hold this family is measured
   against (this project currently only has one real benchmark shape,
   per-symbol; a family with a genuinely different natural benchmark,
   e.g. a 60/40 blend for a multi-asset rotation strategy, states that
   here explicitly rather than silently reusing the wrong one).

## Template

See `docs/strategies/TEMPLATE.md`. Copy it, fill in every section, name
the file after the family (e.g. `docs/strategies/hull_ma_crossover.md`),
commit it in the same PR/commit as the family's own code -- but the doc
comes first in the commit sequence if you're doing this as separate
commits, matching "written before its first backtest" literally.

## Scope note

The 13 classic + 4 ML families already shipped before this convention
existed are not retroactively documented here -- their own module
docstrings (`prometheus/strategy/spec.py`, `prometheus/backtest/ml_signal.py`)
already carry the same citation/rationale information this template
asks for, just inline in code rather than as a separate file. This
convention governs new families going forward.
