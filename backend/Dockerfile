FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production
ENV BACKEND_PORT=5726
ENV ASSET_STORAGE_DIR=/app/storage

WORKDIR /app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN pip install --no-cache-dir -e . \
    && python -m playwright install --with-deps chromium

COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisor/conf.d/wevault.conf

RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/storage /var/log/supervisor

EXPOSE 5726

ENTRYPOINT ["/entrypoint.sh"]
