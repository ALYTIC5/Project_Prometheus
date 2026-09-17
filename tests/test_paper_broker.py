
import pytest

from prometheus.paper.broker import _LIVE_VAR_NAMES, PaperBroker


class FakeCcxtExchange:
    """The ccxt subset PaperBroker uses -- same fake-injection precedent
    as data/ingestion.py's ExchangeClient tests."""

    def __init__(self) -> None:
        self.sandbox_enabled = False
        self.urls = {"api": "https://api.binance.com"}
        self.calls: list[tuple[str, tuple, dict]] = []

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_enabled = enabled
        if enabled:
            self.urls = {"api": "https://testnet.binance.vision/api"}

    def create_order(self, symbol, side, order_type, qty, price=None, params=None):
        self.calls.append(("create_order", (symbol, side, order_type, qty), params or {}))
        return {"id": "exch-1", "status": "open"}

    def fetch_order(self, exchange_order_id, symbol):
        return {"id": exchange_order_id, "status": "closed", "filled": 1.0, "average": 100.0}

    def fetch_open_orders(self, symbol):
        return []

    def cancel_order(self, exchange_order_id, symbol):
        return {"id": exchange_order_id, "status": "canceled"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _LIVE_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_API_KEY", "test-key")
    monkeypatch.setenv("PAPER_API_SECRET", "test-secret")


def test_broker_asserts_testnet_url(monkeypatch):
    broker = PaperBroker(exchange_factory=lambda **_: FakeCcxtExchange())
    assert "testnet" in str(broker.exchange.urls["api"]).lower()


def test_broker_raises_if_live_var_present(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "danger")
    with pytest.raises(RuntimeError, match="live-sounding"):
        PaperBroker(exchange_factory=lambda **_: FakeCcxtExchange())


def test_broker_raises_if_paper_credentials_missing(monkeypatch):
    monkeypatch.delenv("PAPER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PAPER_API_KEY"):
        PaperBroker(exchange_factory=lambda **_: FakeCcxtExchange())


def test_submit_order_calls_create_order_with_client_order_id():
    fake = FakeCcxtExchange()
    broker = PaperBroker(exchange_factory=lambda **_: fake)
    result = broker.submit_order(symbol="BTC/USDT", side="buy", qty=0.01, client_order_id="abc123")
    assert result["id"] == "exch-1"
    assert fake.calls[0][2].get("newClientOrderId") == "abc123"


def test_submit_order_retries_on_network_error_then_succeeds(monkeypatch):
    import ccxt

    from prometheus.core.config import QueueSettings

    class FlakyExchange(FakeCcxtExchange):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def create_order(self, symbol, side, order_type, qty, price=None, params=None):
            self.attempts += 1
            if self.attempts < 2:
                raise ccxt.NetworkError("simulated transient failure")
            return super().create_order(symbol, side, order_type, qty, price, params)

    monkeypatch.setattr("time.sleep", lambda _seconds: None)  # no real delay in tests
    fast_settings = QueueSettings(
        JOB_HEARTBEAT_INTERVAL_SECONDS=1.0,
        JOB_HEARTBEAT_TIMEOUT_SECONDS=5.0,
        JOB_BACKOFF_BASE_SECONDS=0.01,
        JOB_BACKOFF_MAX_SECONDS=0.02,
    )
    fake = FlakyExchange()
    broker = PaperBroker(exchange_factory=lambda **_: fake, queue_settings=fast_settings)
    result = broker.submit_order(symbol="BTC/USDT", side="buy", qty=0.01, client_order_id="retry-1")
    assert result["id"] == "exch-1"
    assert fake.attempts == 2


def test_submit_order_gives_up_after_max_attempts(monkeypatch):
    import ccxt

    from prometheus.core.config import QueueSettings

    class AlwaysFlaky(FakeCcxtExchange):
        def create_order(self, symbol, side, order_type, qty, price=None, params=None):
            raise ccxt.NetworkError("simulated permanent failure")

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    fast_settings = QueueSettings(
        JOB_HEARTBEAT_INTERVAL_SECONDS=1.0,
        JOB_HEARTBEAT_TIMEOUT_SECONDS=5.0,
        JOB_BACKOFF_BASE_SECONDS=0.01,
        JOB_BACKOFF_MAX_SECONDS=0.02,
    )
    broker = PaperBroker(exchange_factory=lambda **_: AlwaysFlaky(), queue_settings=fast_settings)
    with pytest.raises(ccxt.NetworkError):
        broker.submit_order(symbol="BTC/USDT", side="buy", qty=0.01, client_order_id="retry-2")
