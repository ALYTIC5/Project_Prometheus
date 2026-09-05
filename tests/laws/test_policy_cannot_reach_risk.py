"""Law 4, static half: no module that imports ResearchPolicy also
imports the RiskLimits class (as opposed to the read-only RISK_LIMITS
singleton). Importing the class would allow constructing or rebinding a
RiskLimits instance from research-controlled code paths; importing the
singleton only allows reading already-frozen values.
"""
from __future__ import annotations

import ast
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / "core"


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def test_no_module_imports_both_research_policy_and_risk_limits_class() -> None:
    offenders = []
    for path in CORE_DIR.rglob("*.py"):
        if path.name == "config.py":
            continue  # config.py is where both classes are defined; that's fine
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = _imported_names(tree)
        imports_policy = "ResearchPolicy" in names or "load_research_policy" in names
        imports_risk_class = "RiskLimits" in names  # not RISK_LIMITS, the singleton
        if imports_policy and imports_risk_class:
            offenders.append(str(path))
    assert not offenders, (
        f"modules import both ResearchPolicy and the RiskLimits class "
        f"(read-only RISK_LIMITS singleton is fine): {offenders}"
    )
