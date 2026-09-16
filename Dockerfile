# Dockerfile — multi-stage build for Project Prometheus API
# Serves FastAPI + a static Next.js frontend export, in ONE container.
# Cost target: 0.5 vCPU / 512MB per Railway billing ~$10/month.

# --- Frontend build stage ---
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Empty string = same-origin: the frontend and API share one container/
# domain in production, so relative fetch paths ("/world/state") are
# correct and there's no CORS round-trip at all.
ENV NEXT_PUBLIC_API_URL=""
# The art pipeline's real atlases (tools/art/) are verified and committed --
# ship them. Placeholder stays the default everywhere else (registry.ts,
# frontend/src/sprites/registry.ts) so local dev and tests aren't coupled
# to the art assets, per PROMPTS.md's SPRITE_SET=placeholder|production flag.
ENV NEXT_PUBLIC_SPRITE_SET="production"
# PROMPT S: plain dashboard by default. Switching to the isometric world is
# a rebuild with this set to "world" -- the static export (output:'export')
# means this is a build-time choice, not a runtime toggle, same as
# NEXT_PUBLIC_SPRITE_SET above.
ENV NEXT_PUBLIC_UI_MODE="plain"
RUN npm run build

# --- Python builder stage ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
COPY alembic.ini .
COPY prometheus/ prometheus/
# Runtime deps only — ruff/mypy/pytest/pre-commit do not ship to production.
RUN pip install -e .

# --- Production stage ---
FROM python:3.11-slim AS production

# Railway sets RAILWAY_GIT_COMMIT_SHA at runtime already; GIT_SHA is the
# build-arg fallback for other hosts. prometheus.core.provenance.code_sha()
# reads one of the two because the container has no .git directory to
# `git rev-parse` against -- see its docstring.
ARG GIT_SHA=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    GIT_SHA=${GIT_SHA}

WORKDIR /app

# Install runtime deps only
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY prometheus/ prometheus/
COPY config/ config/
COPY alembic.ini .
COPY alembic/ alembic/
COPY pyproject.toml .
COPY .env.example .

# Static frontend export -- served by prometheus/main.py's StaticFiles
# mount at FRONTEND_DIST (<repo>/frontend/out).
COPY --from=frontend-builder /frontend/out frontend/out

# Non-root user
RUN adduser --disabled-password --gecos "" prometheus
USER prometheus

EXPOSE 8000

# RUN_MODE=worker skips the HTTP check entirely -- prometheus/worker.py is
# a one-shot script with no server to curl, and a persistent-service
# healthcheck failing repeatedly against it would make Railway treat a
# successful cron run as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0) if os.environ.get('RUN_MODE') == 'worker' else urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/health/')"

# Railway assigns PORT dynamically at runtime -- shell form so it actually
# expands, unlike exec-form CMD's hardcoded "8000". Migrations run as the
# release step on every deploy, per PROMPTS.md PROMPT 1 Part D ("Alembic
# migrations run on deploy via a release command") -- never destructive,
# alembic upgrade only ever moves forward.
#
# RUN_MODE=worker (PROMPTS.md PROMPT 7's scheduled worker, on a Railway
# Cron Schedule) runs prometheus/worker.py once and exits, instead of the
# default always-on API server -- same env-var-branch pattern the
# frontend build already uses for NEXT_PUBLIC_UI_MODE, chosen because a
# Railway "Custom Start Command" override did not reliably take effect
# for this service in practice (still ran the default CMD); branching
# inside the one CMD both services share is what actually worked.
CMD ["sh", "-c", "alembic upgrade head && if [ \"$RUN_MODE\" = \"worker\" ]; then exec python -m prometheus.worker; else exec uvicorn prometheus.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi"]