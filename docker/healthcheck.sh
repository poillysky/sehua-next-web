#!/bin/sh
# UI: web + api；Worker: api only
set -e
ROLE=$(printf '%s' "${APP_ROLE:-ui}" | tr '[:upper:]' '[:lower:]')
if [ "$ROLE" = "worker" ]; then
  curl -fsS "http://127.0.0.1:8020/health" >/dev/null
  exit 0
fi
curl -fsS "http://127.0.0.1:${WEB_PORT:-3020}/" >/dev/null
curl -fsS "http://127.0.0.1:8020/health" >/dev/null
