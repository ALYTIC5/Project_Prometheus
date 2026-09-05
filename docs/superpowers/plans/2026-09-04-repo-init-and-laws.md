# Project Prometheus — Repo Init & Laws Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Project Prometheus repo skeleton, the two-class config
system that structurally separates risk limits from research policy, the
async DB layer with append-only history enforcement, deterministic
concurrency-safe ID generation, and the `tests/laws/` suite (three real,
four scaffolded-as-xfail), all gated by CI.

**Architecture:** Flat top-level Python packages (`core/`, `data/`,
`strategy/`, `backtest/`, `validation/`, `experiments/`, `research/`,
`paper/`, `world/`, `api/`) under one `prometheus` distribution, `tests/`
sibling at repo root. This task builds only `core/` and `tests/laws/`
scaffolding; the other packages get empty `__init__.py` stubs so the layout
matches CLAUDE.md and later prompts (PROMPTS.md) have somewhere to land.
SQLAlchemy 2.x async for the app, Alembic (sync psycopg driver) for
migrations, Postgres append-only enforced by a real trigger, IDs generated
by an atomic upsert-increment counter table (concurrency-safe without
explicit locking).

**Tech Stack:** Python 3.11, pydantic-settings 2.x, SQLAlchemy 2.x
(asyncpg for runtime, psycopg for Alembic), Alembic, pytest + pytest-asyncio,
ruff, mypy, pre-commit, GitHub Actions.

**Spec:** `CLAUDE.md` (repo root, project constitution) + `PROMPTS.md`
PROMPT 0 (repo root) — this plan implements PROMPT 0 only.

## Global Constraints

- No look-ahead, no survivorship bias, holdout sacred, risk limits outside
  the loop, no real money, history append-only, thresholds change globally
  only — the seven LAWS in CLAUDE.md. This task's law tests cover Law 4
  (risk limits) and Law 6 (append-only) directly; the rest are scaffolded
  as `xfail(strict=True)` pointing at the PROMPTS.md prompt that builds
  the guarded code.
- `RiskLimits` and `ResearchPolicy` MUST live in different classes with
  different loading paths (env-only frozen vs. YAML hot-reload) — no
  shared base class, no shared loader function.
- `RiskLimits` import raises at startup if any of MAX_POSITION_PCT,
  MAX_GROSS_EXPOSURE_PCT, MAX_LEVERAGE, MAX_DAILY_LOSS_PCT,
  MAX_DRAWDOWN_PCT, KILL_SWITCH is missing from the environment.
- `ResearchPolicy` ships with **no invented numeric thresholds** in this
  task — CLAUDE.md: "Inventing numeric thresholds is how the second
  blueprint went wrong." Only the generic versioned hot-reload machinery
  is built now; concrete threshold fields arrive in PROMPT 3
  (validation/scoring.py) with justification, not guesses.
- History is append-only: UPDATE/DELETE on `experiments`, `results`,
  `decisions` raise via a real Postgres trigger, written as an Alembic
  migration — never application-level-only enforcement.
- No Redis, no Docker Compose, no deployment config in this task.
- mypy strict on `core/` (and `validation/`, pre-declared for when that
  package gets real code in PROMPT 3).
- Every new dependency gets a row in `docs/DEPENDENCIES.md`.
- Deterministic core: seeds/config-hash/data-version machinery isn't due
  until later prompts, but nothing built here may depend on wall-clock
  time for anything except `created_at`/`loaded_at` timestamps.
- Verify command for the whole task (run at the end, must be green):
  `pytest tests/laws/ -v && ruff check . && mypy core/`

---

### Task 1: Repo scaffold and tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.pre-commit-config.yaml`
- Create: `.gitignore`
- Create: `core/__init__.py`, `data/__init__.py`, `strategy/__init__.py`,
  `backtest/__init__.py`, `validation/__init__.py`, `experiments/__init__.py`,
  `research/__init__.py`, `paper/__init__.py`, `world/__init__.py`,
  `api/__init__.py`
- Create: `tests/__init__.py`, `tests/laws/__init__.py`
- Create: `config/` (empty dir, populated in Task 3)

**Interfaces:**
- Produces: installable `prometheus` distribution; `ruff check .` and
  `mypy core/` runnable from repo root; pytest discovers `tests/`.

- [ ] **Step 1: Initialize git**

```bash
git init
git config core.autocrlf input
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "prometheus"
version = "0.1.0"
description = "Quantitative research and paper-trading laboratory"
requires-python = ">=3.11,<3.12"
dependencies = [
    "pydantic==2.9.2",
    "pydantic-settings==2.5.2",
    "sqlalchemy==2.0.35",
    "alembic==1.13.3",
    "asyncpg==0.31.0",
    "psycopg[binary]==3.2.3",
    "pyyaml==6.0.2",
]

[project.optional-dependencies]
dev = [
    "ruff==0.6.9",
    "mypy==1.11.2",
    "pytest==8.3.3",
    "pytest-asyncio==0.24.0",
    "pre-commit==3.8.0",
    "types-PyYAML==6.0.12.20240917",
]

[tool.hatch.build.targets.wheel]
packages = [
    "core", "data", "strategy", "backtest", "validation",
    "experiments", "research", "paper", "world", "api",
]

[tool.ruff]
target-version = "py311"
line-length = 100
src = ["core", "data", "strategy", "backtest", "validation",
       "experiments", "research", "paper", "world", "api", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
warn_unused_configs = true
warn_redundant_casts = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = ["core.*", "validation.*"]
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "laws: immutable law tests, see tests/laws/",
]
```

- [ ] **Step 3: Write `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks:
      - id: mypy
        additional_dependencies: ["pydantic==2.9.2", "pydantic-settings==2.5.2", "sqlalchemy==2.0.35"]
        args: ["--config-file=pyproject.toml"]
        files: ^core/
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.env
*.egg-info/
dist/
build/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.coverage

# local tool state — not project source
.claude/
.claude-flow/
.swarm/
.superpowers/
```

- [ ] **Step 5: Create empty package stubs**

```bash
for d in core data strategy backtest validation experiments research paper world api; do
  mkdir -p "$d"
  : > "$d/__init__.py"
done
mkdir -p tests/laws config docs
: > tests/__init__.py
: > tests/laws/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .pre-commit-config.yaml .gitignore \
  core/__init__.py data/__init__.py strategy/__init__.py backtest/__init__.py \
  validation/__init__.py experiments/__init__.py research/__init__.py \
  paper/__init__.py world/__init__.py api/__init__.py \
  tests/__init__.py tests/laws/__init__.py
git commit -m "chore: repo scaffold, tooling config, package skeleton"
```

---

### Task 2: `docs/DEPENDENCIES.md`

**Files:**
- Create: `docs/DEPENDENCIES.md`

**Interfaces:**
- Consumes: the dependency list pinned in Task 1's `pyproject.toml`.

- [ ] **Step 1: Write the dependency ledger**

```markdown
# Dependencies

Every dependency added to this repo is recorded here: what it does, what
it replaces, what it costs (install size / maintenance surface), and why
it isn't stdlib or pandas-only. Pin exact versions in `pyproject.toml`;
this file explains the *why*, `pyproject.toml` is the *what*.

| Name | Version | Purpose | Replaces | Why not stdlib |
|---|---|---|---|---|
| pydantic | 2.9.2 | Typed, validated settings/models for `RiskLimits` and `ResearchPolicy`. Frozen models give us the "attribute assignment raises" guarantee Law 4 needs for free. | Hand-rolled `dataclass` + manual validation | stdlib `dataclasses` don't validate on construction or reject attribute assignment on frozen instances the same way (no field-level validators, no env parsing) |
| pydantic-settings | 2.5.2 | Environment-variable loading for `RiskLimits` with fail-fast-on-missing semantics. | `os.environ` + manual parsing | Manual env parsing silently defaults instead of raising; we need import-time hard failure |
| sqlalchemy | 2.0.35 | Async ORM + Core for `core/db.py`, models for experiments/results/decisions/policy_versions/id_counters. | Raw `asyncpg` queries | Need declarative models Alembic can autogenerate against, and a session API later modules build on |
| alembic | 1.13.3 | Schema migrations, including the append-only trigger DDL. | Hand-run SQL scripts | Need ordered, reversible, version-controlled schema history from day one — Law 6 depends on the trigger existing in every environment identically |
| asyncpg | 0.31.0 | Async Postgres driver for the SQLAlchemy async engine at runtime. | `psycopg` async mode | asyncpg is the SQLAlchemy-recommended, fastest async Postgres driver. Pinned to 0.31.0 rather than 0.29.0 because 0.29.0 ships no prebuilt wheel for the CPython 3.13 interpreter available in this environment and fails to build from source against the 3.13 C API; 0.31.0 ships a cp313 wheel. |
| psycopg[binary] | 3.2.3 | Sync Postgres driver for Alembic (migrations run sync) and the sync test connection used by `test_history_append_only`. | asyncpg in sync mode (not supported) | Alembic's autogenerate and offline/online migration runner assume a sync driver |
| pyyaml | 6.0.2 | Parse `config/research_policy.yaml` for `ResearchPolicy`. | Hand-written YAML subset parser | YAML is a full spec (anchors, multi-doc); stdlib has no YAML parser at all |
| ruff | 0.6.9 (dev) | Lint + format, single fast binary. | flake8 + black + isort | One tool, one config block, far faster on this codebase's eventual size |
| mypy | 1.11.2 (dev) | Static typing, strict on `core/` and `validation/` per CLAUDE.md. | No static typing | CLAUDE.md mandates strict typing on the two law-adjacent packages |
| pytest | 8.3.3 (dev) | Test runner, including `tests/laws/`. | stdlib `unittest` | Fixtures, parametrize, and `xfail(strict=True)` are load-bearing for this repo's law-scaffolding pattern |
| pytest-asyncio | 0.24.0 (dev) | Run `async def test_...` against the async engine/session. | Manual `asyncio.run()` wrapping in every test | Native async test support, `asyncio_mode = "auto"` keeps test code free of boilerplate |
| pre-commit | 3.8.0 (dev) | Run ruff + mypy on every commit locally, matching CI. | CI-only enforcement | Catches law-relevant typing/lint breaks before they're pushed |
```

- [ ] **Step 2: Commit**

```bash
git add docs/DEPENDENCIES.md
git commit -m "docs: dependency ledger"
```

---

### Task 3: `core/config.py` — RiskLimits and ResearchPolicy

**Files:**
- Create: `core/config.py`
- Create: `config/research_policy.yaml`
- Test: `tests/laws/test_risk_limits_immutable.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Produces: `RiskLimits` (class), `RISK_LIMITS` (module-level frozen
  singleton, constructed at import time), `ResearchPolicy` (class),
  `load_research_policy(path: Path, session: Session | None = None) -> ResearchPolicy`.
- Consumes: nothing from earlier tasks (this is the first real module).
- Downstream: `core/db.py` (Task 4) provides `PolicyVersion` ORM model
  that `load_research_policy` writes to when given a session.

- [ ] **Step 1: Write `tests/conftest.py` (test-only env fixture, not real limits)**

```python
"""Session-wide test fixtures. Values here are arbitrary test sentinels,
not production risk limits — those come from real deployment env vars.
"""
import os

# Distinct, easy-to-spot-in-a-diff values so no one mistakes these for
# real limits.
os.environ.setdefault("MAX_POSITION_PCT", "11")
os.environ.setdefault("MAX_GROSS_EXPOSURE_PCT", "22")
os.environ.setdefault("MAX_LEVERAGE", "3")
os.environ.setdefault("MAX_DAILY_LOSS_PCT", "4")
os.environ.setdefault("MAX_DRAWDOWN_PCT", "15")
os.environ.setdefault("KILL_SWITCH", "false")
```

- [ ] **Step 2: Write the failing test `tests/laws/test_risk_limits_immutable.py`**

```python
"""Law 4: risk limits are outside the loop. No generated code, LLM
output, or config mutation may alter them once the process has started.
"""
import pytest
from pydantic import ValidationError

from core.config import RISK_LIMITS, RiskLimits


def test_setting_any_attribute_raises() -> None:
    for field_name in RiskLimits.model_fields:
        with pytest.raises((ValidationError, TypeError)):
            setattr(RISK_LIMITS, field_name, object())


def test_env_change_after_import_does_not_change_running_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RISK_LIMITS.MAX_LEVERAGE
    monkeypatch.setenv("MAX_LEVERAGE", "999999")
    # RISK_LIMITS was constructed once at import time; env changes after
    # that must not reach the already-running instance.
    assert RISK_LIMITS.MAX_LEVERAGE == original


def test_missing_env_var_raises_on_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAX_LEVERAGE", raising=False)
    with pytest.raises(ValidationError):
        RiskLimits()


def test_kill_switch_is_bool_not_stringly_typed() -> None:
    assert isinstance(RISK_LIMITS.KILL_SWITCH, bool)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/laws/test_risk_limits_immutable.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.config'`

- [ ] **Step 4: Write `core/config.py`**

```python
"""Two config classes, deliberately kept apart.

RiskLimits: env-only, frozen, constructed once at import time. There is
no code path — anywhere in this file — that lets a ResearchPolicy value
reach a RiskLimits field. That separation is what makes Law 4
structurally true instead of merely a convention.

ResearchPolicy: YAML-backed, hot-reloadable, versioned. It never touches
os.environ and never constructs a RiskLimits.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RESEARCH_POLICY_PATH = Path("config/research_policy.yaml")


class RiskLimits(BaseSettings):
    """Hard limits. Read once from the environment. Frozen for the life
    of the process — Law 4. Import of this module raises if any field
    is missing from the environment; there is no default fallback,
    because a silently-defaulted risk limit is worse than a crash.
    """

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    MAX_POSITION_PCT: float
    MAX_GROSS_EXPOSURE_PCT: float
    MAX_LEVERAGE: float
    MAX_DAILY_LOSS_PCT: float
    MAX_DRAWDOWN_PCT: float
    KILL_SWITCH: bool

    @field_validator(
        "MAX_POSITION_PCT",
        "MAX_GROSS_EXPOSURE_PCT",
        "MAX_LEVERAGE",
        "MAX_DAILY_LOSS_PCT",
        "MAX_DRAWDOWN_PCT",
    )
    @classmethod
    def _must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("risk limit must be > 0")
        return value


RISK_LIMITS = RiskLimits()  # raises at import time if env is incomplete


class ResearchPolicy(BaseModel):
    """Research-tunable policy, loaded from YAML. Deliberately ships with
    no numeric threshold fields yet — CLAUDE.md is explicit that inventing
    thresholds is how the previous blueprint went wrong. PROMPT 3
    (validation/scoring.py) adds real fields with justification. For now
    this class exists to prove the load/hash/version-row machinery works,
    and to give later prompts one place to hang policy fields off.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1


def _content_hash(raw_yaml: str) -> str:
    return hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest()


def load_research_policy(
    path: Path = DEFAULT_RESEARCH_POLICY_PATH,
    session: Any | None = None,
) -> ResearchPolicy:
    """Load ResearchPolicy from YAML. If `session` is given (an
    `AsyncSession`-like object with `.add()`), writes a `PolicyVersion`
    row with the content hash — every load is versioned, per CLAUDE.md.
    Import-local to avoid a hard dependency from config.py -> db.py at
    module-load time (config must be importable with no DB available).
    """
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    policy = ResearchPolicy(**data)
    if session is not None:
        from core.db import PolicyVersion

        session.add(
            PolicyVersion(content_hash=_content_hash(raw), raw_yaml=raw)
        )
    return policy
```

- [ ] **Step 5: Write `config/research_policy.yaml`**

```yaml
# Research policy. Hot-reloadable, versioned on every load (see
# core.config.load_research_policy). No numeric thresholds live here
# yet — see core/config.py:ResearchPolicy docstring and CLAUDE.md's
# "don't invent thresholds" rule. PROMPT 3 populates real fields.
schema_version: 1
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/laws/test_risk_limits_immutable.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add core/config.py config/research_policy.yaml tests/conftest.py tests/laws/test_risk_limits_immutable.py
git commit -m "feat: RiskLimits and ResearchPolicy, structurally separated (Law 4)"
```

---

### Task 4: `core/db.py` — async engine, session factory, ORM models

**Files:**
- Create: `core/db.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`

**Interfaces:**
- Consumes: nothing from Task 3 at import time (lazy DB config, see
  design note below).
- Produces: `Base` (DeclarativeBase), `Experiment`, `Result`, `Decision`,
  `PolicyVersion`, `IdCounter` ORM models; `get_engine() -> AsyncEngine`;
  `get_session() -> AsyncContextManager[AsyncSession]`.
- Downstream: `core/ids.py` (Task 6) uses `IdCounter`'s table via raw SQL
  against a session; Alembic migrations (Task 5) create these tables'
  DDL plus the append-only triggers.

**Design note:** `RiskLimits` fails fast at import (Task 3) because a
missing risk limit must never be silently tolerated. DB connectivity is a
different kind of dependency — most of `tests/laws/` (the config tests,
the static-analysis test) must be able to run with zero Postgres
available. So `core/db.py` reads `DATABASE_URL` lazily, inside
`get_engine()`, not at module import time.

- [ ] **Step 1: Write `core/db.py`**

```python
"""Async engine, session factory, and the ORM models for the
append-only history tables plus the id-counter table.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    decision: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column()
    raw_yaml: Mapped[str] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdCounter(Base):
    __tablename__ = "id_counters"

    scope: Mapped[str] = mapped_column(primary_key=True)
    next_value: Mapped[int] = mapped_column(default=0)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy: DATABASE_URL is only required once a caller actually needs
    the database, not at import time (tests/laws/ config tests must run
    with no Postgres available).
    """
    global _engine
    if _engine is None:
        database_url = os.environ["DATABASE_URL"]
        _engine = create_async_engine(database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
```

- [ ] **Step 2: Initialize Alembic layout**

```bash
mkdir -p alembic/versions
```

- [ ] **Step 3: Write `alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 4: Write `alembic/env.py`**

```python
"""Alembic runs synchronously (psycopg), even though the app runtime is
async (asyncpg) — this is the standard split; see docs/DEPENDENCIES.md.
DATABASE_URL is read here, not at import time elsewhere, matching the
lazy-DB-config decision in core/db.py.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_database_url() -> str:
    url = os.environ["DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sync_database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: Write `alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 6: Verify mypy passes on the new module**

Run: `mypy core/db.py`
Expected: `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add core/db.py alembic.ini alembic/env.py alembic/script.py.mako alembic/versions
git commit -m "feat: async db engine, session factory, ORM models, alembic scaffold"
```

---

### Task 5: Migrations — timescaledb extension, core tables, append-only triggers

**Files:**
- Create: `alembic/versions/0001_enable_timescaledb.py`
- Create: `alembic/versions/0002_core_tables.py`
- Create: `alembic/versions/0003_append_only_triggers.py`

**Interfaces:**
- Consumes: `core.db.Base.metadata` (Task 4) for table shape reference
  (written by hand here, not autogenerated, since this is the first
  migration and autogenerate needs a live DB diff to be trustworthy).
- Produces: the three tables plus `policy_versions` and `id_counters`,
  and a Postgres trigger function `prevent_history_mutation()` attached
  to `experiments`, `results`, `decisions`.

- [ ] **Step 1: Write `alembic/versions/0001_enable_timescaledb.py`**

```python
"""enable timescaledb extension

Revision ID: 0001
Revises:
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS timescaledb;")
```

- [ ] **Step 2: Write `alembic/versions/0002_core_tables.py`**

```python
"""core tables: experiments, results, decisions, policy_versions, id_counters

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String, sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String, sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("decision", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_yaml", sa.Text, nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "id_counters",
        sa.Column("scope", sa.String, primary_key=True),
        sa.Column("next_value", sa.BigInteger, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("id_counters")
    op.drop_table("policy_versions")
    op.drop_table("decisions")
    op.drop_table("results")
    op.drop_table("experiments")
```

- [ ] **Step 3: Write `alembic/versions/0003_append_only_triggers.py`**

```python
"""append-only enforcement on experiments, results, decisions (Law 6)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLES = ("experiments", "results", "decisions")

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION prevent_history_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'LAW VIOLATION: % on % is forbidden — history is append-only (Law 6)', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_TRIGGER_FN)
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS prevent_history_mutation();")
```

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/0001_enable_timescaledb.py \
  alembic/versions/0002_core_tables.py \
  alembic/versions/0003_append_only_triggers.py
git commit -m "feat: migrations for core tables and append-only trigger (Law 6)"
```

---

### Task 6: `core/ids.py` — deterministic, collision-safe ID generation

**Files:**
- Create: `core/ids.py`

**Interfaces:**
- Consumes: `core.db.AsyncSession` (Task 4), `id_counters` table (Task 5).
- Produces: `next_experiment_id(session, year=None) -> str` (format
  `EXP-YYYY-NNNNNN`), `next_strategy_id(session, family) -> str` (format
  `{FAMILY}-{NNN}`).

- [ ] **Step 1: Write `core/ids.py`**

```python
"""Deterministic, collision-safe ID generation.

Concurrency safety comes from a single atomic upsert-increment statement
against id_counters — no explicit row locking, no read-then-write race.
Two concurrent callers against the same scope always get two different
values because the increment happens inside one atomic statement that
Postgres serializes per-row.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXPERIMENT_ID_RE = re.compile(r"^EXP-\d{4}-\d{6}$")
STRATEGY_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{3}$")
_FAMILY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

_UPSERT_COUNTER = text(
    """
    INSERT INTO id_counters (scope, next_value)
    VALUES (:scope, 1)
    ON CONFLICT (scope) DO UPDATE SET next_value = id_counters.next_value + 1
    RETURNING next_value
    """
)


class IdSequenceExhausted(Exception):
    pass


async def next_experiment_id(session: AsyncSession, year: int | None = None) -> str:
    resolved_year = year if year is not None else datetime.now(UTC).year
    scope = f"experiment:{resolved_year}"
    result = await session.execute(_UPSERT_COUNTER, {"scope": scope})
    n = result.scalar_one()
    if n > 999_999:
        raise IdSequenceExhausted(f"experiment id sequence exhausted for {resolved_year}")
    exp_id = f"EXP-{resolved_year}-{n:06d}"
    await session.commit()
    return exp_id


async def next_strategy_id(session: AsyncSession, family: str) -> str:
    family = family.upper()
    if not _FAMILY_RE.match(family):
        raise ValueError(f"invalid strategy family: {family!r}")
    scope = f"strategy:{family}"
    result = await session.execute(_UPSERT_COUNTER, {"scope": scope})
    n = result.scalar_one()
    if n > 999:
        raise IdSequenceExhausted(f"strategy id sequence exhausted for family {family}")
    strategy_id = f"{family}-{n:03d}"
    await session.commit()
    return strategy_id
```

- [ ] **Step 2: Verify mypy passes**

Run: `mypy core/ids.py`
Expected: `Success: no issues found`

- [ ] **Step 3: Commit**

```bash
git add core/ids.py
git commit -m "feat: deterministic collision-safe experiment/strategy id generation"
```

*(Runtime tests for `next_experiment_id`/`next_strategy_id` against a live
Postgres are integration tests, not law tests — out of scope for
`tests/laws/`. They land with PROMPT 4, experiments/lineage, when there is
a runner to exercise them against.)*

---

### Task 7: `tests/laws/` — append-only test, static policy/risk separation test, xfail stubs

**Files:**
- Create: `tests/laws/test_history_append_only.py`
- Create: `tests/laws/test_policy_cannot_reach_risk.py`
- Create: `tests/laws/test_no_lookahead.py`
- Create: `tests/laws/test_survivorship.py`
- Create: `tests/laws/test_holdout_sacred.py`
- Create: `tests/laws/test_threshold_global.py`

**Interfaces:**
- Consumes: `core.db.Experiment/Result/Decision` (Task 4), the trigger
  from Task 5, `core.config.RiskLimits/ResearchPolicy` (Task 3, for the
  AST check's target names).

- [ ] **Step 1: Write `tests/laws/test_history_append_only.py`**

```python
"""Law 6: history is append-only. UPDATE and DELETE on experiments,
results, decisions raise — enforced by a real Postgres trigger, not
application code, per the migration in alembic/versions/0003_*.

Requires a live Postgres with migrations applied. Skipped (not xfail —
this is missing infrastructure, not missing code) when TEST_DATABASE_URL
isn't set. CI provides it via a postgres service container.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL (Postgres with migrations 0001-0003 applied)",
)


@pytest.fixture()
def engine():
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture()
def experiment_id(engine) -> str:
    exp_id = f"EXP-TEST-{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO experiments (id, status) VALUES (:id, 'pending')"),
            {"id": exp_id},
        )
    return exp_id


def test_update_experiments_raises(engine, experiment_id: str) -> None:
    with pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE experiments SET status = 'changed' WHERE id = :id"),
                {"id": experiment_id},
            )


def test_delete_experiments_raises(engine, experiment_id: str) -> None:
    with pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM experiments WHERE id = :id"), {"id": experiment_id})


@pytest.mark.parametrize("table", ["results", "decisions"])
def test_update_child_tables_raises(engine, experiment_id: str, table: str) -> None:
    value_col = "payload" if table == "results" else "decision"
    with engine.begin() as conn:
        row_id = conn.execute(
            text(
                f"INSERT INTO {table} (experiment_id, {value_col}) "
                f"VALUES (:eid, '{{}}'::jsonb) RETURNING id"
            ),
            {"eid": experiment_id},
        ).scalar_one()
    with pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"):
        with engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {table} SET {value_col} = '{{\"x\":1}}'::jsonb WHERE id = :id"),
                {"id": row_id},
            )


@pytest.mark.parametrize("table", ["results", "decisions"])
def test_delete_child_tables_raises(engine, experiment_id: str, table: str) -> None:
    value_col = "payload" if table == "results" else "decision"
    with engine.begin() as conn:
        row_id = conn.execute(
            text(
                f"INSERT INTO {table} (experiment_id, {value_col}) "
                f"VALUES (:eid, '{{}}'::jsonb) RETURNING id"
            ),
            {"eid": experiment_id},
        ).scalar_one()
    with pytest.raises((DBAPIError, IntegrityError), match="LAW VIOLATION"):
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
```

- [ ] **Step 2: Write `tests/laws/test_policy_cannot_reach_risk.py`**

```python
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
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
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
```

- [ ] **Step 3: Write xfail stub `tests/laws/test_no_lookahead.py`**

```python
"""Law 1: no look-ahead. Real implementation lands with the point-in-time
data layer.
"""
import pytest


@pytest.mark.xfail(
    reason="point-in-time accessor not implemented yet — PROMPTS.md PROMPT 1 (data layer)",
    strict=True,
)
def test_truncated_dataset_matches_full_dataset_features() -> None:
    raise NotImplementedError("data/point_in_time not implemented yet — PROMPT 1")
```

- [ ] **Step 4: Write xfail stub `tests/laws/test_survivorship.py`**

```python
"""Law 2: no survivorship bias. Real implementation lands with the
universe reconstruction module.
"""
import pytest


@pytest.mark.xfail(
    reason="data/universe.py as_of() not implemented yet — PROMPTS.md PROMPT 1 (data layer)",
    strict=True,
)
def test_universe_as_of_includes_delisted_symbols() -> None:
    raise NotImplementedError("data/universe.py not implemented yet — PROMPT 1")
```

- [ ] **Step 5: Write xfail stub `tests/laws/test_holdout_sacred.py`**

```python
"""Law 3: the holdout is sacred. Real implementation lands with the
validation layer's holdout access control.
"""
import pytest


@pytest.mark.xfail(
    reason="validation/holdout.py not implemented yet — PROMPTS.md PROMPT 3 (validation and falsification)",
    strict=True,
)
def test_second_holdout_access_raises() -> None:
    raise NotImplementedError("validation/holdout.py not implemented yet — PROMPT 3")
```

- [ ] **Step 6: Write xfail stub `tests/laws/test_threshold_global.py`**

```python
"""Law 7: thresholds change globally or not at all. Real implementation
lands with validation/scoring.py's policy-versioned weights.
"""
import pytest


@pytest.mark.xfail(
    reason="validation/scoring.py threshold/weight versioning not implemented yet — PROMPTS.md PROMPT 3 (validation and falsification)",
    strict=True,
)
def test_threshold_change_requires_full_corpus_reevaluation() -> None:
    raise NotImplementedError("validation/scoring.py not implemented yet — PROMPT 3")
```

- [ ] **Step 7: Run the full law suite**

Run: `pytest tests/laws/ -v`
Expected: `test_risk_limits_immutable.py` (4 passed),
`test_policy_cannot_reach_risk.py` (1 passed), 4 xfailed
(`test_no_lookahead`, `test_survivorship`, `test_holdout_sacred`,
`test_threshold_global`), `test_history_append_only.py` all skipped
(no `TEST_DATABASE_URL` locally) — 0 failed.

- [ ] **Step 8: Commit**

```bash
git add tests/laws/test_history_append_only.py \
  tests/laws/test_policy_cannot_reach_risk.py \
  tests/laws/test_no_lookahead.py \
  tests/laws/test_survivorship.py \
  tests/laws/test_holdout_sacred.py \
  tests/laws/test_threshold_global.py
git commit -m "test: append-only + policy/risk separation laws, xfail stubs for laws 1/2/3/7"
```

---

### Task 8: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pyproject.toml` dev extras (Task 1), `tests/laws/` (Task 7),
  Alembic migrations (Task 5).

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-type-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy core/
      - run: pytest tests/ -v --ignore=tests/laws

  laws:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: prometheus
          POSTGRES_PASSWORD: prometheus
          POSTGRES_DB: prometheus_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      DATABASE_URL: postgresql+asyncpg://prometheus:prometheus@localhost:5432/prometheus_test
      TEST_DATABASE_URL: postgresql+asyncpg://prometheus:prometheus@localhost:5432/prometheus_test
      MAX_POSITION_PCT: "11"
      MAX_GROSS_EXPOSURE_PCT: "22"
      MAX_LEVERAGE: "3"
      MAX_DAILY_LOSS_PCT: "4"
      MAX_DRAWDOWN_PCT: "15"
      KILL_SWITCH: "false"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: alembic upgrade head
      - name: Run law tests
        run: pytest tests/laws/ -v || (echo "::error::LAW VIOLATION — a tests/laws/ check failed. This gate does not get weakened, skipped, or deleted; fix the code." && exit 1)
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint/type/test job plus dedicated laws job with postgres service"
```

---

### Task 9: Full verification pass

**Files:** none new — this task runs the stated verify command against
everything from Tasks 1-8 and fixes anything it surfaces.

- [ ] **Step 1: Create a local venv and install**

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash; use .venv/bin/activate on Linux/mac
pip install -e ".[dev]"
pre-commit install
```

- [ ] **Step 2: Run the exact verify command from the task**

Run: `pytest tests/laws/ -v && ruff check . && mypy core/`
Expected: all `tests/laws/` pass/xfail/skip as enumerated in Task 7 Step
7, zero ruff violations, zero mypy errors in `core/`.

- [ ] **Step 3: Fix anything the verify command surfaces**

If ruff or mypy report issues, fix them in the offending file from
Tasks 3/4/6 (do not add `# noqa` / `# type: ignore` — fix the actual
typing/lint issue) and re-run Step 2 until clean.

- [ ] **Step 4: Final commit if Step 3 required changes**

```bash
git add -A
git commit -m "fix: address ruff/mypy findings from full verify pass"
```

---

## What this plan deliberately does not build

- No point-in-time data layer, no universe reconstruction (PROMPT 1).
- No strategy spec/backtest engine (PROMPT 2).
- No real validation/holdout/scoring logic or numeric thresholds
  (PROMPT 3) — `ResearchPolicy` is intentionally close to empty.
- No experiments runner/lineage/queue beyond the raw tables and id
  generator (PROMPT 4).
- No Redis, Docker Compose, or deployment config (explicitly excluded by
  this task, and by CLAUDE.md's cost-discipline section generally).
- No integration test exercising `next_experiment_id`/`next_strategy_id`
  under real concurrency — that needs a runner to call it from, which
  doesn't exist until PROMPT 4.

## Uncertain / worth flagging

- Repo layout departs slightly from CLAUDE.md's diagram literally
  nesting `tests/` under `prometheus/`: this plan uses a flat layout
  (`core/`, `tests/`, etc. as siblings at repo root) to match this
  task's own verify command (`mypy core/`, `pytest tests/laws/`) exactly.
  PROMPT 1's verify command (`python -m prometheus.data.ingestion`)
  implies a `prometheus.*` import namespace — that's a decision for
  whoever implements PROMPT 1, not resolved here.
- `test_history_append_only.py` requires live Postgres and is `skipif`
  (not `xfail`) when `TEST_DATABASE_URL` is unset — it's real,
  implemented code, just infra-gated locally. CI always runs it via the
  postgres service container.
