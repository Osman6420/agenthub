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

# The application packages are part of the local project metadata, so they must exist before
# `pip install .`. Copy only package sources here; the bind-mounted development tree still replaces
# them in Compose while immutable builds retain a cacheable dependency/application layer.
COPY pyproject.toml ./
COPY config ./config
COPY apps ./apps
RUN pip install --upgrade pip && pip install .

# Runtime entry point.
COPY manage.py ./

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default role: the ASGI web server. Compose/K8s override the command per role.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
