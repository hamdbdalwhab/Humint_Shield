#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HUMINT Shield backend entrypoint
#
#   web     -> run migrations (optional), then serve with gunicorn/uvicorn
#   worker  -> run a Celery worker
#   beat    -> run Celery beat
#   migrate -> run alembic upgrade head only
#   seed    -> run migrations then print the bootstrap summary
# ---------------------------------------------------------------------------
set -euo pipefail

ROLE="${1:-web}"
shift || true

run_migrations() {
  if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] running alembic upgrade head"
    alembic upgrade head
  fi
}

case "$ROLE" in
  web)
    run_migrations
    workers="${GUNICORN_WORKERS:-4}"
    echo "[entrypoint] starting web with ${workers} gunicorn workers"
    exec gunicorn app.main:app \
      --worker-class uvicorn.workers.UvicornWorker \
      --workers "${workers}" \
      --bind "0.0.0.0:${PORT:-8000}" \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --graceful-timeout 30 \
      --access-logfile - \
      --error-logfile - \
      "$@"
    ;;
  worker)
    echo "[entrypoint] starting celery worker"
    exec celery -A app.worker.celery_app:celery_app worker \
      --loglevel="${LOG_LEVEL:-INFO}" \
      --concurrency="${CELERY_CONCURRENCY:-4}" \
      "$@"
    ;;
  beat)
    echo "[entrypoint] starting celery beat"
    exec celery -A app.worker.celery_app:celery_app beat \
      --loglevel="${LOG_LEVEL:-INFO}" "$@"
    ;;
  migrate)
    exec alembic upgrade head "$@"
    ;;
  seed)
    run_migrations
    echo "[entrypoint] seeding bootstrap data"
    exec python -m app.scripts.seed
    ;;
  *)
    exec "$ROLE" "$@"
    ;;
esac
