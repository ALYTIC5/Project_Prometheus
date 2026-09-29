"""Search-freeze flags (docs/BUILD_PLAN.md D11), read from config/search.yaml.

Fail-safe: a missing file, a missing key, or any value that YAML does not
parse as boolean true means PAUSED. (PyYAML follows YAML 1.1, so `yes`, `on`
and `True` also enable a flag -- each still an explicit edit of this
owner-approval-protected file.) Read fresh on every call -- the worker is a short cron
process, and a stale cached "enabled" must never outlive a deploy that
paused it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_SEARCH_FLAGS_PATH = "config/search.yaml"


@dataclass(frozen=True)
class SearchFlags:
    evolution_enabled: bool
    llm_steps_enabled: bool
    gate_submissions_enabled: bool


def load_search_flags(path: str = DEFAULT_SEARCH_FLAGS_PATH) -> SearchFlags:
    file = Path(path)
    data = yaml.safe_load(file.read_text(encoding="utf-8")) if file.exists() else None
    values = data if isinstance(data, dict) else {}
    return SearchFlags(
        evolution_enabled=values.get("evolution_enabled") is True,
        llm_steps_enabled=values.get("llm_steps_enabled") is True,
        gate_submissions_enabled=values.get("gate_submissions_enabled") is True,
    )
