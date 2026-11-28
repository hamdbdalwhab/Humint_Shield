# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# HUMINT Shield - single-service image for Railway (API + built SPA)
#
# One container serves the FastAPI backend and the compiled React dashboard on
# the same origin, so tracking links, the API and the app all share one URL.
# Migrations run from the entrypoint (RUN_MIGRATIONS), and the worker/beat roles
# reuse the same image with a different start command.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json ./
COPY frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src

# Same-origin deployment: the SPA calls "/api/..." on the host that serves it.
ARG VITE_API_BASE_URL=/
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build


FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    FRONTEND_DIST=/app/frontend/dist

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1000 humint \
 && useradd --uid 1000 --gid humint --create-home humint

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=humint:humint backend/app ./app
COPY --chown=humint:humint backend/alembic ./alembic
COPY --chown=humint:humint backend/alembic.ini backend/pyproject.toml ./
COPY --chown=humint:humint backend/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=humint:humint --from=frontend /app/dist ./frontend/dist
RUN chmod +x /usr/local/bin/entrypoint.sh

USER humint

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8000}/healthz" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
