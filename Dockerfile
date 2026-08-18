# syntax=docker/dockerfile:1
# Single image: web (3020) + api (8020)
# Build: docker build -t sehua-next-web:1.0.16 .

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

# ─── Runtime (Python + Node + supervisord) ─────────────────
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE=/api \
    API_INTERNAL_BASE=http://127.0.0.1:8020 \
    SNS_COOKIE_SECURE=0 \
    WEB_PORT=3020

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg supervisor \
      libvips42 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
  && rm /tmp/requirements.txt

COPY apps/api /app/apps/api
COPY apps/web/src/config /app/apps/web/src/config
COPY config /app/config
RUN mkdir -p /app/data

COPY --from=web-builder /src/public /app/web/public
COPY --from=web-builder /src/.next/standalone /app/web/
COPY --from=web-builder /src/.next/static /app/web/.next/static

COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

EXPOSE 3020
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=8s --start-period=60s --retries=3 \
  CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
