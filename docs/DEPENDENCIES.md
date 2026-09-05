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
| types-PyYAML | 6.0.12.20240917 (dev) | Type stubs for `pyyaml`, so `yaml.safe_load` is typed rather than `Any` under mypy strict on `core/`. | `# type: ignore` on every YAML call site | pyyaml ships no inline types (no `py.typed`); without stubs mypy strict cannot check `core/config.py`'s policy loader at all |
| hatchling | >=1.25 (build) | PEP 517 build backend for `pip install -e .`. | setuptools | setuptools needs `setup.py`/`setup.cfg` plus its own config surface; hatchling reads `pyproject.toml` only. **The one dependency not exactly pinned** — it is a build-time backend that never enters the runtime environment or a backtest, so it is outside the reproducibility boundary that "pin everything" protects. |
