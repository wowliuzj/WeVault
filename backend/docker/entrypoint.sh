#!/usr/bin/env sh
set -eu

cd /app/backend

echo "[wevault] running database migrations"
alembic upgrade head

echo "[wevault] starting api and worker"
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/wevault.conf
