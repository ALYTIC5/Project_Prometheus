"""An injectable clock -- SystemClock for real code paths, FixedClock for
deterministic tests. Neither constructs nor imports RiskLimits or
ResearchPolicy; unrelated to Law 4's separation, kept minimal regardless,
one job per core/ module like everything else here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, fixed: datetime) -> None:
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed
