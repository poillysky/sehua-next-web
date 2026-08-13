#!/bin/sh
set -e
mkdir -p /app/data /app/apps/scrape/data/covers /app/apps/scrape/data/meta
exec "$@"
