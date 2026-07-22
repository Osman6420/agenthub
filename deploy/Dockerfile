# syntax=docker/dockerfile:1.7

# Single immutable image; the container command selects the role
# (web / worker-runtime / worker-ingestion / worker-eval / beat / migrate).
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps kept minimal; psycopg[binary] ships its own libpq.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install third-party dependencies in a layer keyed only by dependency metadata. Minimal package
# placeholders let setuptools read the application metadata without coupling this expensive layer to
# normal source edits. BuildKit retains downloaded wheels across legitimate dependency-layer rebuilds.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip mkdir -p config apps \
    && touch config/__init__.py apps/__init__.py \
    && pip install "setuptools>=68" \
    && pip install .

# Install the real application without dependency resolution. Source-only changes now rebuild this
# cheap layer and cannot download Python packages. The development bind mount still replaces these
# files at runtime, while immutable builds contain the current application source.
COPY config ./config
COPY apps ./apps
RUN pip install --no-build-isolation --no-deps --force-reinstall .

# Runtime entry point.
COPY manage.py ./

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default role: the ASGI web server. Compose/K8s override the command per role.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
