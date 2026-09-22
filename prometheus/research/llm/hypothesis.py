"""prometheus/research/llm/hypothesis.py -- PROMPT 9's LLM hypothesis
generator. NO function here takes a database session -- Law 3 requires
this module to be structurally incapable of opening
validation.holdout.access_holdout() or evaluating its own output
(tests/test_llm_hypothesis_holdout_safety.py enforces both properties by
static inspection, not by trusting a mock to catch every path).

Reuses the 37 EXISTING StrategySpec families (MOMENTUM/BOLLINGER/
VOL_BREAKOUT/RSI/MACD/STOCHASTIC/PARABOLIC_SAR/KELTNER/WILLIAMS_R/CCI/
AWESOME_OSCILLATOR/SUPERTREND/TRIX/KELTNER_REVERSION/BOLLINGER_PCTB/
ZSCORE/IBS/N_DAY_LOW/CONSECUTIVE_DOWN/SMA_DISTANCE/ULTIMATE_OSCILLATOR/
MFI/GAP_FADE/EMA_CROSSOVER/TRIPLE_MA_ALIGNMENT/DEMA_CROSSOVER/
HULL_MA_TREND/KAMA_TREND/TSMOM/ADX_DI_CROSSOVER/AROON_CROSSOVER/
ICHIMOKU_BREAKOUT/VORTEX/LINREG_SLOPE/CHANDELIER_EXIT/SMA200_FILTER/
MA_RIBBON, plus the ML families) -- no new DSL. A malformed LLM response fails
StrategySpec's own model_validator and raises; it is never silently
coerced into an invalid spec.

I3 (final-review fix wave): every failure after the Anthropic call
returns is raised as LLMResponseError, which carries the token usage
that call actually billed. Money is spent the moment `messages.create`
returns, so the caller must be able to log `llm_usage` even when the
response turns out to be unusable -- otherwise the monthly budget cap
under-counts exactly the spend that produced no value.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from prometheus.research.llm.budget import estimate_cost
from prometheus.strategy.spec import FAMILIES, StrategySpec

_SYSTEM_PROMPT = f"""You are a quantitative strategy research assistant.
Given research paper excerpts, propose ONE new trading strategy hypothesis
using EXACTLY one of these families: {", ".join(FAMILIES)}.

Respond with ONLY a JSON object with these exact keys:
- "family": one of {list(FAMILIES)}
- family-specific parameter fields (MOMENTUM: fast_window, slow_window;
  BOLLINGER: lookback_window, band_multiplier; VOL_BREAKOUT: breakout_window,
  exit_window; RSI: rsi_lookback, rsi_oversold; MACD: macd_fast, macd_slow,
  macd_signal; STOCHASTIC: stoch_lookback, stoch_oversold; PARABOLIC_SAR:
  sar_af_start, sar_af_increment, sar_af_max; KELTNER: keltner_lookback,
  keltner_multiplier; WILLIAMS_R: williams_lookback, williams_oversold;
  CCI: cci_lookback, cci_oversold; AWESOME_OSCILLATOR: ao_fast, ao_slow;
  SUPERTREND: supertrend_lookback, supertrend_multiplier; TRIX: trix_lookback;
  KELTNER_REVERSION: keltner_rev_lookback, keltner_rev_multiplier;
  BOLLINGER_PCTB: pctb_lookback, pctb_multiplier, pctb_oversold;
  ZSCORE: zscore_lookback, zscore_oversold; IBS: ibs_oversold;
  N_DAY_LOW: ndaylow_lookback; CONSECUTIVE_DOWN: consecutive_down_days;
  SMA_DISTANCE: sma_dist_lookback, sma_dist_oversold;
  ULTIMATE_OSCILLATOR: uo_short, uo_mid, uo_long, uo_oversold;
  MFI: mfi_lookback, mfi_oversold; GAP_FADE: gap_fade_threshold;
  EMA_CROSSOVER: ema_fast_window, ema_slow_window; TRIPLE_MA_ALIGNMENT:
  tma_fast_window, tma_mid_window, tma_slow_window; DEMA_CROSSOVER:
  dema_fast_window, dema_slow_window; HULL_MA_TREND: hull_lookback;
  KAMA_TREND: kama_lookback, kama_fast_sc, kama_slow_sc; TSMOM:
  tsmom_lookback_days, tsmom_skip_days; ADX_DI_CROSSOVER: adx_lookback;
  AROON_CROSSOVER: aroon_lookback; ICHIMOKU_BREAKOUT: ichimoku_conversion,
  ichimoku_base, ichimoku_span_b; VORTEX: vortex_lookback; LINREG_SLOPE:
  linreg_lookback; CHANDELIER_EXIT: chandelier_lookback,
  chandelier_multiplier; SMA200_FILTER: sma_filter_lookback; MA_RIBBON:
  ribbon_short, ribbon_mid, ribbon_long)
- "expected_horizon": integer, bars ahead this signal is claimed to matter
- "hypothesis_text": a one-paragraph explanation grounded in the provided papers
- "expected_effect": what measurable effect you expect (e.g. "higher Sharpe",
  "lower drawdown") and why

No other text, no markdown fences, just the JSON object."""


class LLMResponseError(ValueError):
    """A response came back from Anthropic (so it was billed) but could
    not be turned into a usable LLMHypothesis -- malformed JSON, a
    missing/unknown field, or a spec that fails StrategySpec's own
    model_validator.

    Subclasses ValueError deliberately: every existing caller catching
    ValueError for "this response was malformed" keeps working
    unchanged. The added `.input_tokens`/`.output_tokens`/`.model`
    attributes are what lets the caller log the llm_usage row for spend
    that has already happened (I3).
    """

    def __init__(
        self, message: str, *, input_tokens: int, output_tokens: int, model: str
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model


@dataclass(frozen=True)
class PaperContext:
    paper_id: int
    key_sections: str


@dataclass(frozen=True)
class LLMHypothesis:
    spec: StrategySpec
    hypothesis_text: str
    expected_effect: str
    paper_ids: list[int]
    model: str
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class _AnthropicClientProtocol(Protocol):
    """Structural type for the Anthropic client -- lets tests pass a
    MagicMock without importing the real anthropic package's own types,
    and keeps this module's public signature honest about what it
    actually needs (a `.messages.create(...)` call), not the whole SDK.

    Must be a SYNCHRONOUS `anthropic.Anthropic()` instance, not
    `AsyncAnthropic()` -- `generate_hypothesis` below calls
    `client.messages.create(...)` without awaiting it, despite being
    declared `async def` itself. This is intentional: Task 5's worker
    constructs a sync client and this function's own `async def` exists
    for its caller's concurrency, not to await this call.

    M1 (final-review fix wave): `messages` is declared as a read-only
    property, not a plain attribute. A plain `messages: Any` is a
    SETTABLE protocol member, which the real `anthropic.Anthropic`
    (whose `.messages` is a read-only property) does not satisfy -- so
    worker.py's `_anthropic_client()` could not be typed against this
    protocol at all. A read-only member is satisfied by both a property
    and an ordinary attribute.
    """

    @property
    def messages(self) -> Any: ...


def _build_user_prompt(symbol: str, timeframe: str, paper_context: list[PaperContext]) -> str:
    excerpts = "\n\n".join(
        f"[Paper {p.paper_id}]\n{p.key_sections}" for p in paper_context
    )
    return (
        f"Symbol: {symbol}\nTimeframe: {timeframe}\n\n"
        f"Research excerpts:\n{excerpts}"
    )


async def generate_hypothesis(
    client: _AnthropicClientProtocol,
    model: str,
    symbol: str,
    timeframe: str,
    paper_context: list[PaperContext],
) -> LLMHypothesis:
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": _build_user_prompt(symbol, timeframe, paper_context),
            }
        ],
    )
    # I3: read the billed token usage FIRST, before touching anything that
    # can fail. Everything below this point is parsing/validation of a
    # response Anthropic has already charged for, so every failure from
    # here on must carry these numbers out to the caller.
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens

    # An unknown family, a missing expected key, unparseable JSON, or a
    # spec StrategySpec's own model_validator rejects (e.g. slow_window <=
    # fast_window) are all the same thing: a malformed LLM response, not a
    # programming error. All of them surface as LLMResponseError -- still a
    # ValueError subclass, so a caller catching ValueError is unaffected,
    # but now carrying the token usage the caller needs to log the spend.
    try:
        raw_text = message.content[0].text
        parsed = json.loads(raw_text)
        family = parsed["family"]
        # NOTE: this family->fields mapping is duplicated from
        # prometheus/strategy/spec.py's _FAMILY_PARAMS (and again in
        # _SYSTEM_PROMPT above); see the cross-reference comment there.
        param_fields = {
            "MOMENTUM": ("fast_window", "slow_window"),
            "BOLLINGER": ("lookback_window", "band_multiplier"),
            "VOL_BREAKOUT": ("breakout_window", "exit_window"),
            "RSI": ("rsi_lookback", "rsi_oversold"),
            "MACD": ("macd_fast", "macd_slow", "macd_signal"),
            "STOCHASTIC": ("stoch_lookback", "stoch_oversold"),
            "PARABOLIC_SAR": ("sar_af_start", "sar_af_increment", "sar_af_max"),
            "KELTNER": ("keltner_lookback", "keltner_multiplier"),
            "WILLIAMS_R": ("williams_lookback", "williams_oversold"),
            "CCI": ("cci_lookback", "cci_oversold"),
            "AWESOME_OSCILLATOR": ("ao_fast", "ao_slow"),
            "SUPERTREND": ("supertrend_lookback", "supertrend_multiplier"),
            "TRIX": ("trix_lookback",),
            "KELTNER_REVERSION": ("keltner_rev_lookback", "keltner_rev_multiplier"),
            "BOLLINGER_PCTB": ("pctb_lookback", "pctb_multiplier", "pctb_oversold"),
            "ZSCORE": ("zscore_lookback", "zscore_oversold"),
            "IBS": ("ibs_oversold",),
            "N_DAY_LOW": ("ndaylow_lookback",),
            "CONSECUTIVE_DOWN": ("consecutive_down_days",),
            "SMA_DISTANCE": ("sma_dist_lookback", "sma_dist_oversold"),
            "ULTIMATE_OSCILLATOR": ("uo_short", "uo_mid", "uo_long", "uo_oversold"),
            "MFI": ("mfi_lookback", "mfi_oversold"),
            "GAP_FADE": ("gap_fade_threshold",),
            "EMA_CROSSOVER": ("ema_fast_window", "ema_slow_window"),
            "TRIPLE_MA_ALIGNMENT": ("tma_fast_window", "tma_mid_window", "tma_slow_window"),
            "DEMA_CROSSOVER": ("dema_fast_window", "dema_slow_window"),
            "HULL_MA_TREND": ("hull_lookback",),
            "KAMA_TREND": ("kama_lookback", "kama_fast_sc", "kama_slow_sc"),
            "TSMOM": ("tsmom_lookback_days", "tsmom_skip_days"),
            "ADX_DI_CROSSOVER": ("adx_lookback",),
            "AROON_CROSSOVER": ("aroon_lookback",),
            "ICHIMOKU_BREAKOUT": ("ichimoku_conversion", "ichimoku_base", "ichimoku_span_b"),
            "VORTEX": ("vortex_lookback",),
            "LINREG_SLOPE": ("linreg_lookback",),
            "CHANDELIER_EXIT": ("chandelier_lookback", "chandelier_multiplier"),
            "SMA200_FILTER": ("sma_filter_lookback",),
            "MA_RIBBON": ("ribbon_short", "ribbon_mid", "ribbon_long"),
        }[family]
        params = {field: parsed[field] for field in param_fields}
        expected_horizon = parsed["expected_horizon"]
        hypothesis_text = parsed["hypothesis_text"]
        expected_effect = parsed["expected_effect"]
        spec = StrategySpec(
            family=family,
            symbol=symbol,
            timeframe=timeframe,
            expected_horizon=expected_horizon,
            source="llm_hypothesis",
            description=hypothesis_text,
            **params,
        )
    except Exception as exc:
        raise LLMResponseError(
            f"LLM response could not be parsed into a valid spec: {exc}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        ) from exc

    return LLMHypothesis(
        spec=spec,
        hypothesis_text=hypothesis_text,
        expected_effect=expected_effect,
        paper_ids=[p.paper_id for p in paper_context],
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=estimate_cost(model, input_tokens=input_tokens, output_tokens=output_tokens),
    )
