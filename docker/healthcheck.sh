#!/bin/sh
# All-in-one health: web + api
set -e
curl -fsS "http://127.0.0.1:${WEB_PORT:-3020}/" >/dev/null
curl -fsS "http://127.0.0.1:8020/health" >/dev/null
