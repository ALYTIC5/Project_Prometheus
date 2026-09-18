"""tests/test_llm_hypothesis_holdout_safety.py -- Law 3. Structural, not a
runtime mock: proves research/llm/hypothesis.py has NO import of anything
that could open a holdout connection, so there is no code path to miss,
not just no path this test happened to exercise."""
from __future__ import annotations

import ast
from pathlib import Path

_HYPOTHESIS_MODULE_PATH = Path("prometheus/research/llm/hypothesis.py")

_FORBIDDEN_MODULES = {
    "prometheus.validation.holdout",
    "prometheus.core.db",
}


def test_hypothesis_module_imports_nothing_that_can_reach_holdout() -> None:
    tree = ast.parse(_HYPOTHESIS_MODULE_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_hit = imported_modules & _FORBIDDEN_MODULES
    assert not forbidden_hit, (
        f"research/llm/hypothesis.py imports {forbidden_hit} -- this module "
        "must never be able to reach validation.holdout.access_holdout or "
        "open a raw DB session (Law 3)"
    )


def test_generate_hypothesis_signature_takes_no_session_parameter() -> None:
    tree = ast.parse(_HYPOTHESIS_MODULE_PATH.read_text(encoding="utf-8"))
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_hypothesis"
    )
    param_names = {arg.arg for arg in func.args.args}
    assert "session" not in param_names
