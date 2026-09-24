"""core/health.py's pure, DB-independent pieces: record_failure's
per-cycle tally and alert_discord_for_threshold_breaches' threshold
logic. flush_cycle's own INSERT is exercised by DB-backed tests
elsewhere (no local Postgres in this environment, same posture as every
other DB-touching module here)."""
from __future__ import annotations

import prometheus.core.health as health


def _reset() -> None:
    health._cycle_failures.clear()
    health._cycle_sample_messages.clear()


def test_record_failure_tallies_by_concern_and_exception_type() -> None:
    _reset()
    health.record_failure("research", ValueError("bad spec"), context="hash=abc")
    health.record_failure("research", ValueError("bad spec"), context="hash=def")
    health.record_failure("research", RuntimeError("boom"), context="hash=ghi")
    health.record_failure("paper", ValueError("bad spec"), context="strategy_id=1")

    assert health._cycle_failures[("research", "ValueError")] == 2
    assert health._cycle_failures[("research", "RuntimeError")] == 1
    assert health._cycle_failures[("paper", "ValueError")] == 1
    _reset()


def test_alert_skips_when_webhook_url_unset(monkeypatch) -> None:
    """No DISCORD_WEBHOOK_URL (the default in every test run and most
    deployments) must be a clean no-op -- never attempt a network call."""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    calls = []
    monkeypatch.setattr(health.urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    row = {
        "concern": "research",
        "exception_type": "ValueError",
        "failure_count": 999,
        "sample_message": "x",
    }
    health.alert_discord_for_threshold_breaches([row])
    assert calls == []


def test_alert_only_fires_above_threshold(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")
    calls = []
    monkeypatch.setattr(health.urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    rows = [
        {
            "concern": "research",
            "exception_type": "ValueError",
            "failure_count": 1,
            "sample_message": "x",
        },
        {
            "concern": "paper",
            "exception_type": "RuntimeError",
            "failure_count": 999,
            "sample_message": "y",
        },
    ]
    health.alert_discord_for_threshold_breaches(rows)
    assert len(calls) == 1  # only the RuntimeError row crossed _ALERT_THRESHOLD
