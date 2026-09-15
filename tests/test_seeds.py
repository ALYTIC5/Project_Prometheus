from __future__ import annotations

from prometheus.core.seeds import derive_seed, rng_for


def test_derive_seed_is_deterministic_across_calls() -> None:
    assert derive_seed("BTC/USDT", "1d", "abc123") == derive_seed("BTC/USDT", "1d", "abc123")


def test_derive_seed_is_sensitive_to_every_part() -> None:
    base = derive_seed("BTC/USDT", "1d", "abc123")
    assert base != derive_seed("ETH/USDT", "1d", "abc123")
    assert base != derive_seed("BTC/USDT", "4h", "abc123")
    assert base != derive_seed("BTC/USDT", "1d", "xyz789")


def test_derive_seed_is_order_sensitive() -> None:
    assert derive_seed("a", "b") != derive_seed("b", "a")


def test_rng_for_same_seed_produces_identical_sequence() -> None:
    seed = derive_seed("BTC/USDT", "1d")
    first = rng_for(seed)
    second = rng_for(seed)
    assert [first.random() for _ in range(5)] == [second.random() for _ in range(5)]
