# syntax=docker/dockerfile:1
# Single image: web (3020) + api (8020) + scrape (9210)
# Build: docker build -t sehua-next-web:1.0.10 .

# ─── Web build ─────────────────────────────────────────────
FROM node:22-bookworm-slim AS web-builder
WORKDIR /src
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE=/api \
    API_INTERNAL_BASE=http://127.0.0.1:8020
RUN npm run build

# ─── Scrape deps ───────────────────────────────────────────
FROM node:22-bookworm-slim AS scrape-deps
WORKDIR /src
COPY apps/scrape/package.json apps/scrape/package-lock.json ./
# tsx 在 devDependencies，运行期仍需
RUN npm ci

# ─── Runtime (Python + Node + supervisord) ─────────────────
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE=/api \
    API_INTERNAL_BASE=http://127.0.0.1:8020 \
    SCRAPE_ORIGIN=http://127.0.0.1:9210 \
    SNS_COOKIE_SECURE=0 \
    PORT=9210 \
    HOST=127.0.0.1 \
    WEB_PORT=3020 \
    SCRAPE_CONCURRENCY=2 \
    SCRAPE_FAST_CONCURRENCY=2 \
    SCRAPE_SLOW_CONCURRENCY=1 \
    SCRAPE_HOST_PARALLEL=1 \
    SCRAPE_MAX_HTML_BYTES=3000000 \
    SCRAPE_MAX_IMAGE_BYTES=5000000 \
    NODE_OPTIONS=--max-old-space-size=512 \
    FLARESOLVERR_MAX_SESSIONS_WARN=1 \
    FLARESOLVERR_MAX_SESSIONS_CRITICAL=2

# Node 22 + supervisord + sharp (libvips) libs
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg supervisor \
      libvips42 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# API Python deps (no Playwright / Chromium)
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
  && rm /tmp/requirements.txt

# Monorepo layout (API ROOT = /app)
COPY apps/api /app/apps/api
COPY apps/web/src/config /app/apps/web/src/config
COPY config /app/config
RUN mkdir -p /app/data /app/apps/scrape/data/covers /app/apps/scrape/data/meta

# Scrape worker
COPY --from=scrape-deps /src/node_modules /app/apps/scrape/node_modules
COPY apps/scrape/package.json apps/scrape/tsconfig.json /app/apps/scrape/
COPY apps/scrape/src /app/apps/scrape/src

# Next standalone
COPY --from=web-builder /src/public /app/web/public
COPY --from=web-builder /src/.next/standalone /app/web/
COPY --from=web-builder /src/.next/static /app/web/.next/static

COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

EXPOSE 3020
VOLUME ["/app/data", "/app/apps/scrape/data"]

HEALTHCHECK --interval=30s --timeout=8s --start-period=90s --retries=3 \
  CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
