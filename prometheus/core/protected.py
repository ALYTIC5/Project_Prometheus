"""Loader for config/protected.yaml (docs/BUILD_PLAN.md P0; CLAUDE.md Law 17).

Only reads and resolves `{ref, key}` references into config/holdout.yaml /
config/costs.yaml. Nothing is wired to these values yet -- P2 makes the risk
section authoritative (environment variables may only tighten it), P5 uses
`plausibility`, P7 `vault`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROTECTED_PATH = "config/protected.yaml"
_REFERABLE = frozenset({"config/holdout.yaml", "config/costs.yaml"})


def _resolve(value: Any, root: Path) -> Any:
    if isinstance(value, dict) and set(value) == {"ref", "key"}:
        if value["ref"] not in _REFERABLE:
            raise ValueError(f"protected.yaml may only reference {sorted(_REFERABLE)}")
        target = yaml.safe_load((root / value["ref"]).read_text(encoding="utf-8"))
        return target[value["key"]]
    if isinstance(value, dict):
        return {k: _resolve(v, root) for k, v in value.items()}
    return value


def load_protected(path: str = DEFAULT_PROTECTED_PATH) -> dict[str, Any]:
    file = Path(path)
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    resolved: dict[str, Any] = _resolve(data, file.resolve().parent.parent)
    return resolved
