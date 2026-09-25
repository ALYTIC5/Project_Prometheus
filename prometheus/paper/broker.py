"""A thin ccxt.binance() wrapper for Binance's real spot testnet
(testnet.binance.vision) -- Law 5: no code path here may ever reach a
live venue. Deliberately not ccxt.binanceus() (data/ingestion.py's
choice, forced by Binance.com's 451 geo-block on market-data endpoints
only): the testnet is a wholly separate sandbox with its own credential
pair, unaffected by that geo-block, and binanceus has no equivalent
testnet to point at.

Two independent guards, both enforced at construction, not deferred to
first use: (1) after set_sandbox_mode(True), the resulting exchange.urls
must actually mention "testnet" -- defends against a future ccxt version
changing sandbox behavior silently; (2) construction raises if ANY
live-sounding credential variable is present in the environment at all,
sandboxed or not -- its mere presence is the failure mode this guards
against, not whether it happens to get used this run.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from prometheus.core.config import QueueSettings
from prometheus.experiments.queue import get_queue_settings

_T = TypeVar("_T")

# Bounded retry attempts for one ccxt call -- this codebase's existing
# convention (experiments/runner.py::enqueue_grid, worker.py's own
# _enqueue_child both call enqueue(..., max_attempts=3, ...)), reused
# here rather than inventing a new retry count.
_MAX_ATTEMPTS = 3

# Known live-credential variable names this guard checks for. Not an
# exhaustive pattern match by design -- an explicit, reviewable list is
# safer for a Law-5-adjacent check than a clever regex that could miss a
# real live-sounding name or, worse, false-positive and block PAPER_*
# entirely. Extend this list if a new live integration is ever added.
_LIVE_VAR_NAMES = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET_KEY",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
)


class CcxtExchange(Protocol):
    """The ccxt subset this module uses -- same "typed subset, fake in
    tests" convention as data/ingestion.py's ExchangeClient."""

    urls: dict[str, Any]

    def set_sandbox_mode(self, enabled: bool) -> None: ...
    def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        qty: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def fetch_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]: ...
    def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]: ...
    def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]: ...


def _default_exchange_factory(**kwargs: Any) -> CcxtExchange:
    import ccxt

    exchange: CcxtExchange = ccxt.binance(kwargs)
    return exchange


class PaperBroker:
    def __init__(
        self,
        *,
        exchange_factory: Callable[..., CcxtExchange] = _default_exchange_factory,
        queue_settings: QueueSettings | None = None,
    ) -> None:
        # DI, same reason as exchange_factory: get_queue_settings() reads
        # required env vars with no defaults (core/config.py), so tests
        # pass an explicit fast QueueSettings instead of needing those
        # vars set -- same posture tests/test_queue_semantics.py already
        # establishes for QueueSettings in tests generally.
        self._queue_settings = queue_settings
        present_live_vars = [name for name in _LIVE_VAR_NAMES if os.environ.get(name)]
        if present_live_vars:
            raise RuntimeError(
                "live-sounding credential variable(s) present in environment: "
                f"{present_live_vars} -- Law 5 forbids any live-money code path; "
                "unset them before running paper trading, even sandboxed."
            )
        api_key = os.environ.get("PAPER_API_KEY")
        api_secret = os.environ.get("PAPER_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError(
                "PAPER_API_KEY and PAPER_API_SECRET must both be set (testnet "
                "credentials from testnet.binance.vision)"
            )

        self.exchange = exchange_factory(apiKey=api_key, secret=api_secret)
        self.exchange.set_sandbox_mode(True)
        if "testnet" not in str(self.exchange.urls.get("api", "")).lower():
            raise RuntimeError(
                "PaperBroker could not confirm testnet mode: "
                f"exchange.urls['api'] = {self.exchange.urls.get('api')!r}"
            )

    def _with_retry(self, call: Callable[[], _T]) -> _T:
        """Retries a transient ccxt.NetworkError with the same backoff
        shape experiments/queue.py's job retry already uses
        (JOB_BACKOFF_BASE_SECONDS / JOB_BACKOFF_MAX_SECONDS), not a new
        backoff constant. Re-raises after _MAX_ATTEMPTS -- this is a
        bounded worker tick, not a process that should hang retrying
        forever. Generic over the call's return type so both a dict
        (submit_order, fetch_order, cancel_order) and a list
        (fetch_open_orders) can share this one retry path."""
        import ccxt

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return call()
            except ccxt.NetworkError as exc:
                last_error = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    break
                # Fetched lazily, only once a retry is actually needed --
                # same lazy posture get_queue_settings() itself documents
                # ("queue env is only required once a caller actually
                # claims/heartbeats/fails a job"). A happy-path call that
                # never hits a NetworkError must not require JOB_BACKOFF_*
                # env vars to be set at all.
                settings = self._queue_settings or get_queue_settings()
                delay = min(
                    settings.JOB_BACKOFF_BASE_SECONDS * (2**attempt),
                    settings.JOB_BACKOFF_MAX_SECONDS,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        client_order_id: str,
        reference_price: float | None = None,
    ) -> dict[str, Any]:
        """reference_price is accepted for interface parity with
        paper.sim_broker.SimBroker and ignored: a testnet market order
        fills at whatever the testnet book gives it."""
        return self._with_retry(
            lambda: self.exchange.create_order(
                symbol, "market", side, qty, params={"newClientOrderId": client_order_id}
            )
        )

    def fetch_order(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]:
        return self._with_retry(lambda: self.exchange.fetch_order(exchange_order_id, symbol))

    def fetch_open_orders(self, *, symbol: str) -> list[dict[str, Any]]:
        return self._with_retry(lambda: self.exchange.fetch_open_orders(symbol))

    def cancel_order(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]:
        return self._with_retry(lambda: self.exchange.cancel_order(exchange_order_id, symbol))
