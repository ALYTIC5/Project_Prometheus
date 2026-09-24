"""tests/test_rotation_generate.py"""
from __future__ import annotations

from prometheus.research.rotation_generate import (
    ROTATION_GRID_GENERATORS,
    generate_accelerating_dual_momentum_grid,
    generate_daa_grid,
    generate_dual_momentum_grid,
    generate_equal_weight_grid,
    generate_fifty_two_week_high_grid,
    generate_gtaa_grid,
    generate_min_variance_grid,
    generate_paa_grid,
    generate_relative_strength_grid,
    generate_residual_momentum_grid,
    generate_risk_parity_grid,
    generate_sector_mean_reversion_grid,
    generate_sector_momentum_grid,
)

_SECTORS = {"XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"}


def test_equal_weight_grid_is_one_spec_over_11_sectors() -> None:
    grid = generate_equal_weight_grid()
    assert len(grid) == 1
    assert set(grid[0].universe) == _SECTORS
    assert grid[0].rebalance_frequency_days == 21


def test_sector_momentum_grid_is_6_specs() -> None:
    grid = generate_sector_momentum_grid()
    assert len(grid) == 6
    assert {s.lookback_days for s in grid} == {63, 126, 252}
    assert {s.top_n for s in grid} == {3, 5}


def test_relative_strength_grid_fixes_top_n_at_3() -> None:
    grid = generate_relative_strength_grid()
    assert len(grid) == 3
    assert all(s.top_n == 3 for s in grid)


def test_sector_mean_reversion_grid_is_4_specs() -> None:
    grid = generate_sector_mean_reversion_grid()
    assert len(grid) == 4
    assert {s.lookback_days for s in grid} == {21, 63}


def test_dual_momentum_grid_is_one_spec_over_gem_universe() -> None:
    grid = generate_dual_momentum_grid()
    assert len(grid) == 1
    assert grid[0].universe == ("SPY", "EFA", "TLT")
    assert grid[0].lookback_days == 252


def test_gtaa_grid_is_one_spec_over_5_asset_universe() -> None:
    grid = generate_gtaa_grid()
    assert len(grid) == 1
    assert grid[0].universe == ("SPY", "EFA", "IEF", "VNQ", "GLD")
    assert grid[0].lookback_days == 210


def test_daa_grid_uses_kellers_own_breadth_variants() -> None:
    grid = generate_daa_grid()
    assert len(grid) == 3
    assert {s.top_n for s in grid} == {1, 2, 6}
    assert grid[0].universe[:2] == ("EEM", "IEF")
    assert grid[0].universe[-1] == "IEF"


def test_paa_grid_sweeps_top_n_and_protection_factor() -> None:
    grid = generate_paa_grid()
    assert len(grid) == 6
    assert {s.top_n for s in grid} == {1, 6}
    assert {s.protection_factor for s in grid} == {0.5, 1.0, 2.0}
    assert all(s.lookback_days == 210 for s in grid)


def test_accelerating_dual_momentum_grid_is_one_spec() -> None:
    grid = generate_accelerating_dual_momentum_grid()
    assert len(grid) == 1
    assert grid[0].universe == ("QQQ", "EFA", "IEF")


def test_risk_parity_grid_sweeps_lookback() -> None:
    grid = generate_risk_parity_grid()
    assert len(grid) == 2
    assert {s.lookback_days for s in grid} == {63, 126}
    assert set(grid[0].universe) == _SECTORS


def test_min_variance_grid_sweeps_lookback() -> None:
    grid = generate_min_variance_grid()
    assert len(grid) == 2
    assert {s.lookback_days for s in grid} == {63, 126}


def test_fifty_two_week_high_grid_uses_252_day_window() -> None:
    grid = generate_fifty_two_week_high_grid()
    assert len(grid) == 2
    assert all(s.lookback_days == 252 for s in grid)
    assert {s.top_n for s in grid} == {3, 5}


def test_residual_momentum_grid_benchmark_is_first_universe_member() -> None:
    grid = generate_residual_momentum_grid()
    assert len(grid) == 3
    assert all(s.universe[0] == "SPY" for s in grid)
    assert all(s.top_n == 3 for s in grid)


def test_all_13_generators_registered() -> None:
    assert len(ROTATION_GRID_GENERATORS) == 13
    total_specs = sum(len(gen()) for gen in ROTATION_GRID_GENERATORS)
    assert total_specs == 1 + 6 + 3 + 4 + 1 + 1 + 3 + 6 + 1 + 2 + 2 + 2 + 3  # 35 total
