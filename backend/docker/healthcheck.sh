#!/usr/bin/env bash
# Container healthcheck for the shared web/worker image.
#
# Only the web role listens on a port, so anything else reports healthy
# immediately; otherwise a Celery worker would be killed by the runtime's
# health probe for never answering HTTP.
set -euo pipefail

if [ "${SERVICE_ROLE:-web}" != "web" ]; then
  exit 0
fi

exec curl -fsS "http://localhost:${PORT:-8000}/healthz"
