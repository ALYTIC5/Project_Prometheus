"""prometheus/worker.py's _run_ablation -- the daily-cadence concern
that actually invokes the six real component ablations. Pure orchestration
tests: every real register_*_component call is mocked out, since their
own real behavior is already covered by tests/test_ablation_ml_component.py
and the pre-existing evolution/LLM ablation test files.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus.worker import _run_ablation


def _fake_result(verdict: str) -> SimpleNamespace:
    return SimpleNamespace(verdict=verdict)


@asynccontextmanager
async def _fake_get_session():
    # _run_ablation opens its own session per registration via
    # get_session() -- every register_*_component call is itself mocked
    # out in these tests, so the yielded session object is never really
    # used, just needs to exist for the `async with` to succeed without
    # a real DATABASE_URL.
    yield MagicMock()


async def test_run_ablation_calls_all_six_registrations_with_bounded_symbols() -> None:
    with (
        patch("prometheus.worker.get_session", _fake_get_session),
        patch(
            "prometheus.worker.load_universe_symbols",
            return_value=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        ),
        patch(
            "prometheus.worker.register_evolution_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ) as mock_evolution,
        patch(
            "prometheus.worker.register_llm_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ) as mock_llm,
        patch(
            "prometheus.worker.register_ml_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ) as mock_rf,
        patch(
            "prometheus.worker.register_gradient_boosting_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ) as mock_gb,
        patch(
            "prometheus.worker.register_logistic_regression_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ) as mock_lr,
        patch(
            "prometheus.worker.register_svm_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ) as mock_svm,
    ):
        verdicts = await _run_ablation()

    # Bounded to _ABLATION_SYMBOLS_LIMIT (2), not the full 3-symbol universe.
    for mock_fn in (mock_evolution, mock_llm, mock_rf, mock_gb, mock_lr, mock_svm):
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["symbols"] == ["BTC/USDT", "ETH/USDT"]

    assert len(verdicts) == 6
    assert all(v.endswith("=UNPROVEN") for v in verdicts)


async def test_run_ablation_isolates_one_registration_failure() -> None:
    """One component's ablation raising must not prevent the other five
    from recording their own verdict this cycle -- same 'one concern's
    failure can't sink the others' isolation run_once() already applies
    to ingest/research/paper/llm_ingestion."""
    with (
        patch("prometheus.worker.get_session", _fake_get_session),
        patch("prometheus.worker.load_universe_symbols", return_value=["BTC/USDT"]),
        patch(
            "prometheus.worker.register_evolution_component",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "prometheus.worker.register_llm_component",
            new=AsyncMock(return_value=_fake_result("NEUTRAL")),
        ),
        patch(
            "prometheus.worker.register_ml_component",
            new=AsyncMock(return_value=_fake_result("VALUABLE")),
        ),
        patch(
            "prometheus.worker.register_gradient_boosting_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ),
        patch(
            "prometheus.worker.register_logistic_regression_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ),
        patch(
            "prometheus.worker.register_svm_component",
            new=AsyncMock(return_value=_fake_result("UNPROVEN")),
        ),
    ):
        verdicts = await _run_ablation()

    # Five succeeded (evolution's failure produced no verdict entry, not a crash).
    assert len(verdicts) == 5
    assert "random_forest=VALUABLE" in verdicts


async def test_run_ablation_with_empty_universe_returns_nothing() -> None:
    with patch("prometheus.worker.load_universe_symbols", return_value=[]):
        verdicts = await _run_ablation()
    assert verdicts == []
