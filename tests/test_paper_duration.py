from prometheus.paper.duration import required_observation_days, required_paper_trading_duration


def test_required_observation_days_basic():
    # 1.0 turnover/day historically -> 1 trade/day roughly -> 20 trades
    # needed means ~20 days.
    days = required_observation_days(
        minimum_trades=20, historical_turnover=100.0, historical_window_days=100
    )
    assert days == 20


def test_required_observation_days_no_historical_activity_returns_none():
    assert (
        required_observation_days(
            minimum_trades=20, historical_turnover=0.0, historical_window_days=100
        )
        is None
    )


def test_required_paper_trading_duration_end_to_end():
    days = required_paper_trading_duration(
        sharpe_hat=1.5,
        benchmark_sharpe=0.0,
        skewness=-0.2,
        kurtosis=3.2,
        confidence=0.95,
        historical_turnover=50.0,
        historical_window_days=200,
    )
    assert days is not None
    assert days > 0


def test_required_paper_trading_duration_none_when_mintrl_none():
    # sharpe_hat == benchmark_sharpe -> minimum_track_record_length
    # returns None -> this must propagate, not raise or fabricate 0.
    assert (
        required_paper_trading_duration(
            sharpe_hat=0.3,
            benchmark_sharpe=0.3,
            skewness=0.0,
            kurtosis=3.0,
            confidence=0.95,
            historical_turnover=50.0,
            historical_window_days=200,
        )
        is None
    )
