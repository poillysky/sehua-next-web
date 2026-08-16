#!/bin/sh
set -e
mkdir -p /app/data /app/apps/scrape/data/covers /app/apps/scrape/data/meta

# NAS 常把 scrape.env 挂到 apps/scrape/.env：若宿主机文件不存在，Docker 会建成目录，tsx 读 .env 即崩 → UI「离线」
# 优先用真实文件；若被挂成目录则摘掉，再从 /app/config/scrape.env 拷一份（可选）
ENV_FILE=/app/apps/scrape/.env
CFG_ENV=/app/config/scrape.env
if [ -d "$ENV_FILE" ]; then
  echo "[entrypoint] warn: $ENV_FILE is a directory (missing host file?). removing"
  rm -rf "$ENV_FILE"
fi
if [ ! -f "$ENV_FILE" ] && [ -f "$CFG_ENV" ]; then
  cp "$CFG_ENV" "$ENV_FILE"
  echo "[entrypoint] seeded scrape .env from $CFG_ENV"
fi

# 刮削 + maker-fs 并发会吃大量 FD；默认 1024 易触发
# "unable to open database file" / Errno 24 Too many open files
if command -v ulimit >/dev/null 2>&1; then
  ulimit -n 65535 2>/dev/null || ulimit -n 1048576 2>/dev/null || true
fi
exec "$@"
