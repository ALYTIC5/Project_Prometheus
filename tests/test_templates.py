from __future__ import annotations

from prometheus.research.templates import seed_specs_by_family
from prometheus.strategy.spec import FAMILIES


def test_seed_specs_by_family_covers_every_family() -> None:
    grouped = seed_specs_by_family()
    assert set(grouped.keys()) == set(FAMILIES)
    for family, specs in grouped.items():
        assert len(specs) > 0
        assert all(spec.family == family for spec in specs)
