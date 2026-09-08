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

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/health/')"

# Railway assigns PORT dynamically at runtime -- shell form so it actually
# expands, unlike exec-form CMD's hardcoded "8000". Migrations run as the
# release step on every deploy, per PROMPTS.md PROMPT 1 Part D ("Alembic
# migrations run on deploy via a release command") -- never destructive,
# alembic upgrade only ever moves forward.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn prometheus.main:app --host 0.0.0.0 --port ${PORT:-8000}"]