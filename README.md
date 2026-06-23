# WeVault

WeVault is a WeChat Official Account content vault for collecting, preserving, and exporting articles.

The first version focuses on a small, reliable loop:

- Multi-user platform login
- WeChat Official Account authorization
- Public account source management
- Article list collection
- Selected article content collection
- Long-term storage of HTML, Markdown, plain text, and assets
- Text-preserving export to PDF, DOCX, and Markdown

## Project Structure

```text
WeVault/
  backend/   FastAPI service, workers, crawlers, exporters
  frontend/  Vue 3 user-facing UI
  console/   Vue 3 administrator console
  docs/      Product and architecture design documents
```

The current UI demo can be opened directly at `frontend/demo.html`.

The Vue frontend scaffold lives in `frontend/`:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

By default, the frontend runs on `http://localhost:5725` and calls the backend at `http://localhost:5726/api/v1`.
If Cloudflare Turnstile is enabled on the backend, set
`VITE_TURNSTILE_SITE_KEY` in `frontend/.env` before starting or building the
frontend.

The administrator console scaffold lives in `console/`:

```bash
cd console
cp .env.example .env
npm install
npm run dev
```

By default, the console runs on `http://localhost:5727` and calls the same
backend API. The first administrator account is initialized by backend
environment variables:

```bash
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=change-this-admin-password
ADMIN_DISPLAY_NAME=Administrator
```

The backend creates or updates that administrator during startup when both
`ADMIN_EMAIL` and `ADMIN_PASSWORD` are set.

Cloudflare Turnstile is optional in local development. When
`CLOUDFLARE_TURNSTILE_SECRET_KEY` is set in the backend environment, user login,
user registration, and administrator console login require a valid Turnstile
token. The frontend and console must be started or built with
`VITE_TURNSTILE_SITE_KEY`.

The FastAPI backend scaffold lives in `backend/`:

```bash
cd backend
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.run
```

Collection tasks are executed by a separate worker process. Start it in another
terminal after the backend dependencies and database migrations are ready:

```bash
cd backend
source .venv/bin/activate
python -m app.worker
```

The current worker uses PostgreSQL as a lightweight queue. It polls
`collection_tasks` for `pending` rows, locks tasks with
`SELECT ... FOR UPDATE SKIP LOCKED`, marks them `running`, then updates them to
`succeeded`, `failed`, or `cancelled`. Multiple worker processes or concurrent
slots can run at the same time without claiming the same task.

Useful worker options:

```bash
python -m app.worker --queue all --concurrency 2
python -m app.worker --queue fetch --concurrency 2
python -m app.worker --queue export --concurrency 4
```

The poll interval, default queue, and default concurrency are controlled by
`WORKER_POLL_INTERVAL_SECONDS`, `WORKER_QUEUE`, and `WORKER_CONCURRENCY` in
`backend/.env`.

Automatic source collection does not require `crontab`. When the worker runs
with `--queue all` or `--queue fetch`, it checks enabled public account sources
once per day after `AUTO_FETCH_SCHEDULE_TIME` server local time, defaulting to
`03:00`. For each active source with
automatic collection enabled, the worker creates a normal `fetch_source_articles`
task for the last `AUTO_FETCH_LOOKBACK_DAYS` days, defaulting to 2, skips
existing articles, and uses the source's `auto_fetch_content` setting to decide
whether to fetch article正文. If the active WeChat authorization session is
expired or invalid, that run is skipped and the automatic collection switch is
kept enabled so it can resume after re-authorization.

For local debugging, the worker prints task lifecycle messages to the console,
including whether a pending task was found, which task was selected, article
list page requests, saved article counts, cancellation, success, and failure
details.

Export jobs are also handled by the worker. The export pipeline supports PDF,
DOCX, and Markdown; selecting multiple formats creates one ZIP bundle for
download. If an article's正文 has not been fetched yet, the export task fetches it
before generating the file. Generated files are stored under `storage/exports/`
and downloaded from the Export Center. Export files and export job records expire
after `EXPORT_FILE_TTL_DAYS` days, defaulting to 14 days; the worker checks for
expired exports every `EXPORT_CLEANUP_INTERVAL_SECONDS` seconds.

Manual export cleanup:

```bash
python -m app.worker --cleanup-exports
```

## Docker Backend Deployment

For VPS deployments where the host Nginx serves `frontend/dist` and proxies
`/api/v1` to a Dockerized backend, see
[`docs/deployment-docker-backend.md`](docs/deployment-docker-backend.md).

Quick backend container start:

```bash
cp .env.production.example .env.production
docker compose -f docker-compose.backend.yml --env-file .env.production up -d --build
```

## Planned Stack

- Frontend: Vue 3, TypeScript, Vite, Naive UI
- Backend: FastAPI, SQLAlchemy 2.x, Alembic
- Database: PostgreSQL
- Current queue: PostgreSQL polling worker
- Future queue/cache: Redis with Celery or Dramatiq when concurrency needs grow
- Browser automation: Playwright Chromium
- Export: Chromium PDF, DOCX generator, Markdown package

## MVP Scope

Version 1 intentionally skips comment collection, global settings, workspace
collaboration, NotebookLM integration, and AI analysis. Those features can be
added after the collection, storage, and export pipeline is stable.
