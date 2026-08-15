#!/bin/sh
set -e
mkdir -p /app/data /app/apps/scrape/data/covers /app/apps/scrape/data/meta
# 刮削 + maker-fs 并发会吃大量 FD；默认 1024 易触发
# "unable to open database file" / Errno 24 Too many open files
if command -v ulimit >/dev/null 2>&1; then
  ulimit -n 65535 2>/dev/null || ulimit -n 1048576 2>/dev/null || true
fi
exec "$@"
