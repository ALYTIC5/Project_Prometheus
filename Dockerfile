# Dockerfile — multi-stage build for Project Prometheus API
# Serves FastAPI + (optionally) a static Next.js frontend export.
# Cost target: 0.5 vCPU / 512MB per Railway billing ~$10/month.

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

# Non-root user
RUN adduser --disabled-password --gecos "" prometheus
USER prometheus

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')"

CMD ["uvicorn", "prometheus.main:app", "--host", "0.0.0.0", "--port", "8000"]