# Docker Backend Deployment

This deployment runs only the WeVault backend in Docker:

- FastAPI API
- background worker
- Playwright Chromium

The frontend is built on the VPS host and served by the host Nginx. PostgreSQL
runs on the host or on an external database server.

## 1. Prepare The VPS

Ubuntu 24.04 packages:

```bash
sudo apt update
sudo apt install -y git nginx postgresql postgresql-contrib nodejs npm docker.io docker-compose-v2
sudo systemctl enable --now docker nginx postgresql
```

If `docker-compose-v2` is not available from your Ubuntu mirror, install Docker
from Docker's official apt repository and then install `docker-compose-plugin`
from that repository.

## 2. Prepare PostgreSQL

```bash
sudo -u postgres psql
```

```sql
CREATE USER wevault WITH PASSWORD 'replace-with-a-strong-password';
CREATE DATABASE wevault OWNER wevault;
\q
```

If PostgreSQL runs on the host and Docker connects through
`host.docker.internal`, make sure PostgreSQL listens on a non-loopback address
that Docker can reach. On a typical Docker bridge setup, the host is reachable
from containers at `172.17.0.1`:

```text
listen_addresses = '127.0.0.1,172.17.0.1'
```

Then restrict access in `pg_hba.conf` to the Docker bridge subnet. For example:

```text
host    wevault    wevault    172.17.0.0/16    scram-sha-256
```

Reload PostgreSQL after editing its config.

## 3. Build The Frontend On The Host

```bash
cd /opt/wevault/frontend
cp .env.example .env
```

For same-origin Nginx routing:

```env
VITE_API_BASE_URL=/api/v1
```

Build:

```bash
npm install
npm run build
```

## 4. Configure The Backend Container

```bash
cd /opt/wevault
cp .env.production.example .env.production
```

Edit `.env.production`:

```env
DATABASE_URL=postgresql+asyncpg://wevault:replace-with-a-strong-password@host.docker.internal:5432/wevault
SECRET_KEY=replace-with-a-long-random-secret
ASSET_STORAGE_DIR=/app/storage
WORKER_CONCURRENCY=2
```

## 5. Start The Backend Container

```bash
cd /opt/wevault
docker compose -f docker-compose.backend.yml --env-file .env.production up -d --build
```

For dry-run validation with the example file:

```bash
WEVAULT_ENV_FILE=.env.production.example \
  docker compose -f docker-compose.backend.yml --env-file .env.production.example config
```

The container automatically runs:

```bash
alembic upgrade head
```

Then Supervisor starts both:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 5726
python -m app.worker --queue all --concurrency ${WORKER_CONCURRENCY}
```

Automatic source collection is handled by this long-running worker process; no
host `crontab` is required. With `WORKER_QUEUE=all` or `WORKER_QUEUE=fetch`, the
worker checks enabled public account sources once per day after 03:00 server
local time and creates normal article-list collection tasks for the last 2 days.
If the WeChat authorization session is expired or invalid, automatic collection
is disabled for the affected source.

Check logs:

```bash
docker compose -f docker-compose.backend.yml logs -f wevault-backend
```

Manual export cleanup:

```bash
docker compose -f docker-compose.backend.yml exec wevault-backend \
  python -m app.worker --cleanup-exports
```

## 6. Configure Host Nginx

Create `/etc/nginx/sites-available/wevault`:

```nginx
server {
    listen 80;
    server_name wevault.example.com;

    root /opt/wevault/frontend/dist;
    index index.html;

    client_max_body_size 50m;

    location /api/v1/ {
        proxy_pass http://127.0.0.1:5726/api/v1/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/wevault /etc/nginx/sites-enabled/wevault
sudo nginx -t
sudo systemctl reload nginx
```

Add HTTPS with Certbot, Caddy, or your preferred reverse proxy setup.

## 7. Update Deployment

```bash
cd /opt/wevault
git pull
cd frontend
npm install
npm run build
cd ..
docker compose -f docker-compose.backend.yml --env-file .env.production up -d --build
```
