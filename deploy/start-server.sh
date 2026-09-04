#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ] && [ -z "${DATABASE_HOST:-}" ]; then
    mkdir -p "${DATA_DIR:-数据}"
fi

if [ -x .venv/bin/uvicorn ]; then
    UVICORN=.venv/bin/uvicorn
else
    UVICORN=uvicorn
fi

exec "$UVICORN" server.app:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers