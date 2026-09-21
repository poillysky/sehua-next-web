#!/bin/sh
set -e
mkdir -p /app/data

# 刮削并发会吃大量 FD；默认 1024 易触发
# "unable to open database file" / Errno 24 Too many open files
if command -v ulimit >/dev/null 2>&1; then
  ulimit -n 65535 2>/dev/null || ulimit -n 1048576 2>/dev/null || true
fi

ROLE=$(printf '%s' "${APP_ROLE:-ui}" | tr '[:upper:]' '[:lower:]')
case "$ROLE" in
  worker)
    CONF=/etc/supervisor/supervisord-worker.conf
    ;;
  *)
    CONF=/etc/supervisor/supervisord.conf
    ;;
esac

# Dockerfile CMD 是 supervisord -n -c <默认conf>。
# 必须丢掉 CMD 里的 -c，否则会盖掉按 APP_ROLE 选中的配置。
if [ "$#" -eq 0 ] || [ "$1" = "supervisord" ]; then
  exec supervisord -n -c "$CONF"
fi

exec "$@"
