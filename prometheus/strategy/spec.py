"""Five concrete, fully-parameterized strategy families: SMA crossover
(momentum), Bollinger mean-reversion, Donchian-channel volatility
breakout, Wilder's RSI mean-reversion, and Appel's MACD trend-following
-- the "classic templates" PROMPT 6 names as the baseline every future
component must beat. All five are cited, standard technical
constructions, not invented formulas. RSI/MACD added later, same
justification and same touch points (backtest/engine.py's signal
dispatch, research/generate.py's grid, research/llm/hypothesis.py's
family->fields mapping) VOL_BREAKOUT already established.

Deterministic, no free text, no LLM -- CLAUDE.md's own stated null
hypothesis is that LLM-generated research loses to static baselines until
proven otherwise, so the first strategy types here are not an LLM's output.

Carry (PROMPT 6's fourth named template) is deliberately NOT built: it
needs futures funding-rate or spot-futures basis data, and this project's
ccxt pipeline is spot-OHLCV only -- no futures ingestion exists anywhere
in prometheus/data/. Building it would mean fabricating a signal from
data that doesn't exist. See docs/DEFERRED.md.

Generalized (PROMPT 3) with the fields that have real, non-decorative
content today: parent_id (spec-level lineage -- which spec this was
mutated from; distinct from experiments.parent_experiment_id, which
already tracks *experiment* lineage), description, source (provenance),
and expected_horizon (required -- real input to Prompt 5's
validation/decay.py, not decoration).

Generalized again (PROMPT 6) with per-family optional parameter fields
rather than a discriminated union of spec types -- same shape fast_window/
slow_window already had, just widened, so config_hash(), the DB column
shape, and every existing call site typed against a single StrategySpec
stay unchanged. A model_validator enforces that a spec only ever carries
the parameters its own family actually uses -- MOMENTUM's
lookback_window/band_multiplier/breakout_window/exit_window all stay
None, and so on for each family -- so "this field is set" always means
"this family reads it," never decorative always-None scaffolding.

Deliberately NOT added: strategy_id (stays a DB-assigned id from
core.ids.next_strategy_id, generated at persistence time -- inside the
frozen, hashed spec it would be circular, since the id doesn't exist
until after the spec is first persisted), universe (redundant with
symbol until an engine can actually trade more than one -- see
docs/DEFERRED.md), features/signals/entry_rules/exit_rules/
position_sizing/risk_rules (the DSL surface -- strategy/dsl.py is
deliberately deferred to Prompt 9, and empty placeholder fields with no
consumer would be exactly the decorative scaffolding CLAUDE.md's
engineering rules forbid), lineage (redundant with parent_id here and
with the real experiment-lineage tracking in experiments/lineage.py).
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, model_validator

FAMILY_MOMENTUM = "MOMENTUM"
FAMILY_BOLLINGER = "BOLLINGER"
FAMILY_VOL_BREAKOUT = "VOL_BREAKOUT"
FAMILY_RSI = "RSI"
FAMILY_MACD = "MACD"
FAMILY_RANDOM_FOREST = "RANDOM_FOREST"
FAMILIES = (FAMILY_MOMENTUM, FAMILY_BOLLINGER, FAMILY_VOL_BREAKOUT, FAMILY_RSI, FAMILY_MACD)

# Each family's own parameter fields -- the set a spec of that family MUST
# have set, with every other family's fields left None. Enforced by
# _params_match_family below, not left to convention: a spec claiming two
# families' parameters at once (or none) is a real construction error, not
# something the engine should silently guess about.
#
# DRIFT WARNING: prometheus/research/llm/hypothesis.py keeps its own copy
# of this family->fields mapping in TWO places (the _SYSTEM_PROMPT's
# field listing, and the param_fields dict inside generate_hypothesis).
# Adding a family here means updating both of those in step, or the LLM
# generator silently keeps proposing only the old families.
_FAMILY_PARAMS: dict[str, tuple[str, ...]] = {
    FAMILY_MOMENTUM: ("fast_window", "slow_window"),
    FAMILY_BOLLINGER: ("lookback_window", "band_multiplier"),
    FAMILY_VOL_BREAKOUT: ("breakout_window", "exit_window"),
    FAMILY_RSI: ("rsi_lookback", "rsi_oversold"),
    FAMILY_MACD: ("macd_fast", "macd_slow", "macd_signal"),
    FAMILY_RANDOM_FOREST: ("rf_train_window", "rf_retrain_interval", "rf_predict_threshold"),
}
_ALL_PARAM_FIELDS = tuple(
    field for fields in _FAMILY_PARAMS.values() for field in fields
)

# The fields that determine backtest behavior -- what config_hash()
# identifies. Deliberately excludes parent_id/description/source/
# expected_horizon: those are metadata and provenance, not identity. Two
# mutations from different parents that land on the same executable
# parameters ARE the same strategy for dedup purposes ("this fingerprint
# prevents rediscovering the same strategy forever") -- hashing the whole
# model would break that the moment lineage or wording differs. Widened
# (PROMPT 6) to every family's param fields -- a None for a field this
# spec's family doesn't use still serializes consistently, so two MOMENTUM
# specs keep hashing identically to each other and never collide with a
# BOLLINGER spec (different family string, different field set populated).
_IDENTITY_FIELDS = ("family", "symbol", "timeframe", *_ALL_PARAM_FIELDS)


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str = FAMILY_MOMENTUM
    symbol: str
    timeframe: str

    # MOMENTUM (SMA crossover).
    fast_window: int | None = None
    slow_window: int | None = None
    # BOLLINGER (mean ± band_multiplier * std over lookback_window --
    # John Bollinger's own standard construction, not an invented one).
    lookback_window: int | None = None
    band_multiplier: float | None = None
    # VOL_BREAKOUT (Donchian channel, the Turtle Trading convention: a
    # longer entry window, a shorter exit window).
    breakout_window: int | None = None
    exit_window: int | None = None
    # RSI (Wilder's own construction): long when RSI drops below the
    # oversold threshold, flat otherwise.
    rsi_lookback: int | None = None
    rsi_oversold: float | None = None
    # MACD (Gerald Appel's own construction): long when the fast/slow EMA
    # difference crosses above its own signal-line EMA.
    macd_fast: int | None = None
    macd_slow: int | None = None
    macd_signal: int | None = None
    # RANDOM_FOREST: a walk-forward-retrained RandomForestClassifier
    # predicting next-bar direction. Deliberately NOT in FAMILIES (see
    # docs/superpowers/specs/2026-09-20-random-forest-strategy-design.md)
    # -- a generation component measured against the baseline, not a
    # member of it.
    rf_train_window: int | None = None
    rf_retrain_interval: int | None = None
    rf_predict_threshold: float | None = None

    # How many bars ahead this strategy's signal is claimed to matter.
    # Required, no default: CLAUDE.md's own rule is "don't invent
    # thresholds silently" -- a generator must state its own horizon
    # claim, not receive a silently-chosen one.
    expected_horizon: int

    parent_id: str | None = None
    description: str = ""
    source: str = "deterministic_grid"

    @model_validator(mode="after")
    def _params_match_family(self) -> StrategySpec:
        if self.family not in _FAMILY_PARAMS:
            raise ValueError(f"unknown family: {self.family!r}")
        required = _FAMILY_PARAMS[self.family]
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"family {self.family!r} requires {missing}")
        foreign = [
            f
            for f in _ALL_PARAM_FIELDS
            if f not in required and getattr(self, f) is not None
        ]
        if foreign:
            raise ValueError(f"family {self.family!r} must not set {foreign}")
        if self.family == FAMILY_MOMENTUM and self.slow_window <= self.fast_window:  # type: ignore[operator]
            raise ValueError("slow_window must be greater than fast_window")
        if self.family == FAMILY_VOL_BREAKOUT and self.exit_window >= self.breakout_window:  # type: ignore[operator]
            raise ValueError("exit_window must be less than breakout_window")
        if self.family == FAMILY_MACD and self.macd_fast >= self.macd_slow:  # type: ignore[operator]
            raise ValueError("macd_fast must be less than macd_slow")
        if self.family == FAMILY_RANDOM_FOREST:
            if self.rf_train_window <= 0:  # type: ignore[operator]
                raise ValueError("rf_train_window must be positive")
            if not (0 < self.rf_retrain_interval <= self.rf_train_window):  # type: ignore[operator]
                raise ValueError("rf_retrain_interval must be in (0, rf_train_window]")
            if not (0.0 < self.rf_predict_threshold < 1.0):  # type: ignore[operator]
                raise ValueError("rf_predict_threshold must be in (0, 1)")
        return self

    @property
    def parameters(self) -> dict[str, float]:
        """A generic, family-agnostic view of this spec's tunable
        parameters -- the family's own populated fields, not a separately
        stored dict, so there is nothing to desync. Prompt 7's
        complexity-counting code can call this without knowing this
        family's specific field names."""
        return {
            field: float(getattr(self, field))
            for field in _FAMILY_PARAMS[self.family]
        }

    def config_hash(self) -> str:
        """Deterministic identity for this exact spec's BEHAVIOR (see
        _IDENTITY_FIELDS) -- same pattern as
        prometheus.data.versioning.compute_content_hash: a stable hash of
        canonical content, not Python's salted-per-process hash()."""
        canonical = self.model_dump(include=set(_IDENTITY_FIELDS))
        canonical_json = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def with_updates(self, **updates: object) -> StrategySpec:
        """A validated copy -- NOT `model_copy(update=...)`, which is
        documented Pydantic v2 behavior to skip validation entirely and
        was confirmed, by actually testing it, to happily produce a spec
        with slow_window <= fast_window. Going through the real
        constructor re-runs `_params_match_family`, so PROMPT 7's
        mutation/crossover code gets a real error here instead of a
        silently-invalid spec surfacing confusion somewhere downstream."""
        return StrategySpec(**{**self.model_dump(), **updates})
