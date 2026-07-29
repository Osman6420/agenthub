# syntax=docker/dockerfile:1.7

# The default target is the application image. `static-runtime` is a second immutable target built
# from the same source and release id for OpenShift static delivery.
FROM node:20.20.0-bookworm-slim AS frontend-build

ENV NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN --mount=type=cache,target=/root/.npm npm --prefix frontend ci

COPY frontend ./frontend
RUN npm --prefix frontend run typecheck \
    && npm --prefix frontend test \
    && npm --prefix frontend run build

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
COPY docs/architecture/workflow-dsl-llm-guide.md ./docs/architecture/workflow-dsl-llm-guide.md
COPY --from=frontend-build /build/apps/builder/static/builder ./apps/builder/static/builder
RUN pip install --no-build-isolation --no-deps --force-reinstall .

# Runtime entry points and static-artifact verifier.
COPY manage.py ./
COPY scripts/verify_static_assets.py ./scripts/verify_static_assets.py

# The collector never becomes a runtime image. It fails the build if the locked frontend output or
# collected tree is missing, unsafe, empty, or inconsistent with the release id.
FROM base AS static-collector

ARG STATIC_RELEASE_ID=development

RUN DJANGO_SETTINGS_MODULE=config.settings.base \
        python manage.py collectstatic --noinput --clear \
    && find /app/staticfiles -type f -name '*.map' -delete \
    && python scripts/verify_static_assets.py \
        --root /app/staticfiles \
        --release-id "${STATIC_RELEASE_ID}" \
        --manifest /app/staticfiles/asset-manifest.json

# Owner-approved production dependency: the upstream non-root Nginx image. Organization release
# automation must resolve the base and resulting image by digest before promotion.
FROM nginxinc/nginx-unprivileged:1.28.1-alpine AS static-runtime

ARG STATIC_RELEASE_ID=development

USER root
COPY deploy/static/nginx.conf /etc/nginx/nginx.conf
COPY --from=static-collector /app/staticfiles /opt/agenthub-static
RUN case "${STATIC_RELEASE_ID}" in \
        ""|*[!A-Za-z0-9._-]*) echo "invalid STATIC_RELEASE_ID" >&2; exit 1 ;; \
    esac \
    && test "${#STATIC_RELEASE_ID}" -le 128 \
    && mkdir -p "/usr/share/nginx/html/static/${STATIC_RELEASE_ID}" \
    && cp -a /opt/agenthub-static/. "/usr/share/nginx/html/static/${STATIC_RELEASE_ID}/" \
    && printf 'ok\n' > /usr/share/nginx/html/healthz \
    && rm -rf /opt/agenthub-static \
    && find /usr/share/nginx/html -type d -exec chmod 0555 {} + \
    && find /usr/share/nginx/html -type f -exec chmod 0444 {} +

LABEL org.opencontainers.image.title="AgentHub static assets" \
      org.opencontainers.image.description="Immutable collected static assets for AgentHub" \
      org.opencontainers.image.revision="${STATIC_RELEASE_ID}"

USER 101

EXPOSE 8080

# Single immutable application image; the container command selects the role
# (web / worker-runtime / worker-ingestion / worker-eval / beat / migrate).
FROM base AS application

ARG STATIC_RELEASE_ID=development

ENV AGENTHUB_IMAGE_RELEASE_ID="${STATIC_RELEASE_ID}"

RUN case "${STATIC_RELEASE_ID}" in \
        ""|*[!A-Za-z0-9._-]*) echo "invalid STATIC_RELEASE_ID" >&2; exit 1 ;; \
    esac \
    && test "${#STATIC_RELEASE_ID}" -le 128 \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

LABEL org.opencontainers.image.revision="${STATIC_RELEASE_ID}"

USER appuser

EXPOSE 8000

# Default role: the ASGI web server. Compose/K8s override the command per role.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
