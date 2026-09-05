"""Law 4, static half: no module that imports ResearchPolicy also
imports the RiskLimits class (as opposed to the read-only RISK_LIMITS
singleton). Importing the class would allow constructing or rebinding a
RiskLimits instance from research-controlled code paths; importing the
singleton only allows reading already-frozen values.

Scoped to the whole `prometheus/` package, not just `prometheus/core/` —
Law 4's actual threat model is research-controlled code paths
(`research/`, `experiments/`, `strategy/`), not the config module itself.
Catches both `from prometheus.core.config import RiskLimits` and
`import prometheus.core.config` (or `from prometheus.core import config`)
followed by attribute access like `config.RiskLimits(...)`.
"""
from __future__ import annotations

import ast
from pathlib import Path

PROMETHEUS_DIR = Path(__file__).resolve().parents[2] / "prometheus"
_EXEMPT = {PROMETHEUS_DIR / "core" / "config.py"}

_POLICY_NAMES = {"ResearchPolicy", "load_research_policy"}
_RISK_CLASS_NAME = "RiskLimits"  # not RISK_LIMITS, the read-only singleton


def _root_name(node: ast.expr) -> str | None:
    """Walk an attribute chain (e.g. `a.b.c`) back to its root Name."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _analyze(tree: ast.Module) -> tuple[bool, bool]:
    """Returns (imports_policy, imports_risk_class)."""
    direct_names: set[str] = set()
    # Local names bound to "the core.config module" (or an ancestor package
    # of it), via `import prometheus.core.config [as x]` or
    # `from prometheus.core import config [as x]`.
    module_roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                direct_names.add(bound)
                is_config_module = module.endswith("core.config") or (
                    module.endswith("core") and alias.name == "config"
                )
                if is_config_module:
                    module_roots.add(bound)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                direct_names.add(alias.asname or alias.name)
                if "core.config" in alias.name or alias.name.endswith("core"):
                    # `import prometheus.core.config` binds the top-level
                    # package name (`prometheus`) unless aliased.
                    top_level = alias.asname or alias.name.split(".")[0]
                    module_roots.add(top_level)

    imports_policy = bool(direct_names & _POLICY_NAMES)
    imports_risk_class = _RISK_CLASS_NAME in direct_names

    if module_roots:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _root_name(node) in module_roots:
                if node.attr in _POLICY_NAMES:
                    imports_policy = True
                elif node.attr == _RISK_CLASS_NAME:
                    imports_risk_class = True

    return imports_policy, imports_risk_class


def test_no_module_imports_both_research_policy_and_risk_limits_class() -> None:
    offenders = []
    for path in PROMETHEUS_DIR.rglob("*.py"):
        if path in _EXEMPT:
            continue  # core/config.py is where both classes are defined; that's fine
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_policy, imports_risk_class = _analyze(tree)
        if imports_policy and imports_risk_class:
            offenders.append(str(path))
    assert not offenders, (
        f"modules import both ResearchPolicy and the RiskLimits class "
        f"(read-only RISK_LIMITS singleton is fine): {offenders}"
    )
