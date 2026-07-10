# Single immutable image; the container command selects the role
# (web / worker-runtime / worker-ingestion / worker-eval / beat / migrate).
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps kept minimal; psycopg[binary] ships its own libpq.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Application code.
COPY manage.py ./
COPY config ./config
COPY apps ./apps

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default role: the ASGI web server. Compose/K8s override the command per role.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
