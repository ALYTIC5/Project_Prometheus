"""Law 9: the evaluator is out of reach. No research, generation, or LLM
process may write to evaluation code, validation state, the holdout, the
canary registry, or the alpha-wealth ledger.

Static half (always runs): nothing under prometheus/research/ imports
judging code or the unrestricted DB session getters, and no SQL string in
it writes a judging table, reads the raw population tables (which would
let it diff them against the canary-free views), or names the evaluator
schema.

DB half (needs TEST_DATABASE_URL + RESEARCH_DATABASE_URL, migration 0024):
the research role gets a real Postgres permission error on each of those
operations, and can still do its actual job.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

RESEARCH_DIR = Path(__file__).resolve().parents[2] / "prometheus" / "research"

_FORBIDDEN_MODULE_PREFIXES = (
    "prometheus.validation",
    "prometheus.experiments.runner",
    "prometheus.experiments.ablation",
    "prometheus.experiments.violations",
    "prometheus.paper",
)
_FORBIDDEN_DB_NAMES = {
    "get_engine",
    "get_session",
    "get_session_factory",
    "get_holdout_engine",
    "get_holdout_session",
    "get_holdout_session_factory",
}
_JUDGING_TABLES = (
    "strategies|experiments|results|decisions|validation_results|component_registry|"
    "research_violations|holdout_access_log|ablation_trials|benchmark_equity|"
    "policy_versions|paper_findings"
)
_FORBIDDEN_SQL = (
    re.compile(rf"\b(UPDATE|DELETE\s+FROM|INSERT\s+INTO|TRUNCATE)\s+({_JUDGING_TABLES})\b", re.I),
    re.compile(r"\b(FROM|JOIN)\s+(strategies|experiments)\b", re.I),
    re.compile(r"\bevaluator\.", re.I),
    re.compile(r"\bholdout\.", re.I),
)


def _research_modules() -> list[Path]:
    return sorted(RESEARCH_DIR.rglob("*.py"))


def test_research_imports_no_judging_code_or_unrestricted_sessions() -> None:
    offenders: list[str] = []
    for path in _research_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(_FORBIDDEN_MODULE_PREFIXES):
                    offenders.append(f"{path.name}: from {module} import ...")
                if module == "prometheus.core.db":
                    bad = {a.name for a in node.names} & _FORBIDDEN_DB_NAMES
                    if bad:
                        offenders.append(f"{path.name}: from prometheus.core.db import {bad}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(_FORBIDDEN_MODULE_PREFIXES):
                        offenders.append(f"{path.name}: import {alias.name}")
    assert not offenders, f"research code reaches the evaluator: {offenders}"


_LOOKS_LIKE_SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)\b")


def test_research_sql_never_touches_judging_tables() -> None:
    """Scans string constants that contain an upper-case SQL verb, so prose
    in docstrings that merely mentions a table is not mistaken for SQL."""
    offenders: list[str] = []
    for path in _research_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _LOOKS_LIKE_SQL.search(node.value)
            ):
                for pattern in _FORBIDDEN_SQL:
                    match = pattern.search(node.value)
                    if match:
                        offenders.append(f"{path.name}:{node.lineno}: {match.group(0)!r}")
    assert not offenders, f"research SQL reaches judging state: {offenders}"


_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("RESEARCH_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL and RESEARCH_DATABASE_URL (migration 0024's role)",
)


def _research_engine():  # type: ignore[no-untyped-def]
    return create_engine(
        os.environ["RESEARCH_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    )


@_needs_db
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE strategies SET status = 'VALIDATED' WHERE false",
        "INSERT INTO decisions (experiment_id, decision) VALUES ('x', '{}'::jsonb)",
        "INSERT INTO validation_results (strategy_fingerprint) VALUES ('x')",
        "INSERT INTO research_violations (violation_type, detail) VALUES ('X', '{}'::jsonb)",
        "UPDATE component_registry SET verdict = 'VALUABLE' WHERE false",
        "INSERT INTO results (experiment_id, payload) VALUES ('x', '{}'::jsonb)",
        "SELECT 1 FROM strategies LIMIT 1",
        "SELECT 1 FROM experiments LIMIT 1",
        "SELECT 1 FROM evaluator.canary_registry LIMIT 1",
        "INSERT INTO evaluator.promotion_halts (event, reason) VALUES ('CLEAR', 'x')",
        "SELECT 1 FROM holdout.ohlcv_bars LIMIT 1",
    ],
)
def test_research_role_is_denied(statement: str) -> None:
    engine = _research_engine()
    try:
        with (
            pytest.raises((DBAPIError, ProgrammingError), match="permission denied"),
            engine.connect() as conn,
        ):
            conn.execute(text(statement))
    finally:
        engine.dispose()


@_needs_db
@pytest.mark.parametrize(
    "statement",
    [
        "SELECT count(*) FROM breedable_strategies",
        "SELECT count(*) FROM breedable_scores",
        "SELECT count(*) FROM research_papers",
        "SELECT verdict FROM component_registry LIMIT 1",
    ],
)
def test_research_role_can_still_do_research(statement: str) -> None:
    engine = _research_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text(statement))
    finally:
        engine.dispose()
