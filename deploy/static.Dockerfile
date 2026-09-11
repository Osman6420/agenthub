# syntax=docker/dockerfile:1.7

# Standalone static-runtime image for OpenShift Docker builders that cannot select a multi-stage
# target. Keep this build contract aligned with deploy/Dockerfile; tests enforce the shared inputs.
ARG NODE_BASE_IMAGE=node:20.20.0-bookworm-slim
ARG PYTHON_BASE_IMAGE=python:3.13-slim
ARG NGINX_BASE_IMAGE=nginxinc/nginx-unprivileged:1.28.1-alpine

FROM ${NODE_BASE_IMAGE} AS frontend-build

ENV NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN --mount=type=cache,target=/root/.npm npm --prefix frontend ci

COPY frontend ./frontend
RUN npm --prefix frontend run typecheck \
    && npm --prefix frontend test \
    && npm --prefix frontend run build

FROM ${PYTHON_BASE_IMAGE} AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip mkdir -p config apps \
    && touch config/__init__.py apps/__init__.py \
    && pip install "setuptools>=68" \
    && pip install .

COPY config ./config
COPY apps ./apps
COPY docs/architecture/workflow-dsl-llm-guide.md ./docs/architecture/workflow-dsl-llm-guide.md
COPY --from=frontend-build /build/apps/builder/static/builder ./apps/builder/static/builder
RUN pip install --no-build-isolation --no-deps --force-reinstall .

COPY manage.py ./
COPY scripts/verify_static_assets.py ./scripts/verify_static_assets.py

FROM base AS static-collector

ARG STATIC_RELEASE_ID=development

RUN DJANGO_SETTINGS_MODULE=config.settings.base \
        python manage.py collectstatic --noinput --clear \
    && find /app/staticfiles -type f -name '*.map' -delete \
    && python scripts/verify_static_assets.py \
        --root /app/staticfiles \
        --release-id "${STATIC_RELEASE_ID}" \
        --manifest /app/staticfiles/asset-manifest.json

FROM ${NGINX_BASE_IMAGE}

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
