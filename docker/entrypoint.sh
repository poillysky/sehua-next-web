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

if [ "$#" -eq 0 ]; then
  exec supervisord -n -c "$CONF"
fi

# docker CMD 默认是 supervisord …；按角色改配置文件
if [ "$1" = "supervisord" ]; then
  shift
  exec supervisord -n -c "$CONF" "$@"
fi

exec "$@"
