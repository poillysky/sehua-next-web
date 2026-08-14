#!/bin/sh
# All-in-one health: web + api + scrape
set -e
curl -fsS "http://127.0.0.1:${WEB_PORT:-3020}/" >/dev/null
curl -fsS "http://127.0.0.1:8020/health" >/dev/null
curl -fsS "http://127.0.0.1:9210/health" >/dev/null
