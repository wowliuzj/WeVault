# WeVault Architecture Draft

## Product Goal

WeVault is a personal and team-ready archive for WeChat Official Account content. It turns public account article streams into a durable knowledge base with clean text, assets, and high-quality exports.

## First Version Scope

The MVP should include:

- Platform user login
- One active WeChat authorization per user, while keeping the data model ready for multiple authorizations
- Public account source discovery by account search or article URL parsing
- Article list synchronization after a source is added
- Manual article content collection from selected articles
- Optional source-level automatic content collection
- Article library with collection status
- Export center for PDF, DOCX, and Markdown

The MVP should not include:

- Article comment collection
- Global settings management
- Workspace/team collaboration
- NotebookLM upload
- AI analysis
- Vector search
- Plugin marketplace

## High-Level Modules

```text
Frontend
  Vue admin console

Backend API
  User auth
  WeChat authorization
  Source management
  Article library
  Task management
  Export management

Worker
  Article list collection
  Article content collection
  Export generation

Storage
  PostgreSQL metadata and content
  Redis queue/cache/locks
  Local or object storage for assets and exports
```

## Core Flow

```text
User logs in
  -> User authorizes a WeChat Official Account session
  -> User adds a public account source
  -> System fetches article list
  -> Articles enter pending content status
  -> User selects articles to fetch
  -> Worker fetches article HTML, assets, text, and Markdown
  -> User exports selected articles as PDF, DOCX, or Markdown
```

## Collection Strategy

Public account sources should support two discovery methods:

- Search by public account name
- Parse from an existing article URL

After a source is added, WeVault should fetch the article list first. Full article content should be a separate task. Each source can define whether content should be fetched automatically after list synchronization.

Recommended source settings:

- `auto_fetch_content`
- `fetch_limit_per_run`
- `fetch_since_days`

Default behavior should be conservative:

- Fetch article list automatically
- Do not fetch article content automatically

## Content Pipeline

Article content should be stored before export. Export should never depend on screenshots of the original page.

```text
Original article page
  -> raw_html
  -> clean_html
  -> markdown
  -> plain_text
  -> local assets
  -> PDF / DOCX / Markdown export
```

PDF should be generated from clean HTML with text preserved. DOCX should be generated from clean HTML or Markdown, not by converting from a screenshot PDF.

## Initial Data Model

Main tables:

- `users`
- `wechat_accounts`
- `wechat_sessions`
- `wechat_sources`
- `articles`
- `article_contents`
- `collection_tasks`
- `export_jobs`
- `export_files`

Important uniqueness rules:

- One active WeChat authorization per user in version 1
- Data model allows multiple WeChat authorizations per user later
- Article uniqueness should use source plus WeChat article identifiers, such as `source_id + appmsgid + itemidx`

## Task Types

Recommended task types:

- `fetch_source_articles`
- `fetch_article_content`
- `export_articles`

Tasks should record status, progress, retry count, error message, and timestamps.

Recommended statuses:

- `pending`
- `running`
- `succeeded`
- `failed`
- `cancelled`

## Current Worker Implementation

The first implementation uses PostgreSQL as a lightweight task queue. This keeps
the MVP simple and avoids introducing Redis or a dedicated queue service before
the collection pipeline is stable.

Run the worker as a separate long-running process:

```bash
cd backend
source .venv/bin/activate
python -m app.worker
```

The worker can also run multiple concurrent slots in one process, or consume a
specific task queue:

```bash
python -m app.worker --queue fetch --concurrency 2
python -m app.worker --queue export --concurrency 4
```

The API server and worker are intentionally separate processes:

- The API server handles user actions, creates `collection_tasks`, and exposes
  start, stop, and delete operations.
- The worker polls `collection_tasks`, picks `pending` tasks with row-level
  locks, and performs the actual collection work.

Current task acquisition flow:

```text
Worker loop
  -> poll collection_tasks where status = pending
  -> lock one row with SELECT ... FOR UPDATE SKIP LOCKED
  -> mark task running and set started_at
  -> execute task handler
  -> set succeeded/failed/cancelled and finished_at
```

Each concurrent worker slot repeats this flow independently. PostgreSQL
`SKIP LOCKED` keeps multiple slots or multiple worker processes from claiming
the same task.

The polling interval is configured with:

```text
WORKER_POLL_INTERVAL_SECONDS=2
WORKER_CONCURRENCY=1
WORKER_QUEUE=all
```

Supported queue names:

- `all`: consume every supported task type
- `fetch`: consume collection/content-fetch tasks
- `export`: consume export tasks

Automatic source collection is part of the long-running worker, not a separate
cron job. Workers running with `all` or `fetch` check enabled public account
sources once per day after 03:00 server local time. Each eligible source gets a
normal `fetch_source_articles` task with:

- `range`: `custom`
- `start_date`: server local date minus 2 days
- `end_date`: server local date
- `limit`: `0`
- `skip_existing`: `true`
- `trigger`: `auto`

The task reuses the source's `auto_fetch_content` setting. If the user's active
WeChat authorization is expired or invalid, automatic collection is disabled for
that source instead of repeatedly creating failing tasks.

Current supported worker handler:

- `fetch_source_articles`: fetches the article list for one public account
  source through the user's active WeChat authorization session and upserts
  article metadata into `articles`.
- `fetch_article_content`: fetches saved articles'正文 content and stores clean
  HTML, Markdown, plain text, and cached assets.
- `export_articles`: fetches missing article content when needed, then exports
  selected articles to PDF, DOCX, Markdown, or a multi-format ZIP bundle and
  records downloadable files in `export_files`.
- `export cleanup`: deletes expired export files, `export_files`,
  `export_jobs`, and related export task rows after `EXPORT_FILE_TTL_DAYS`
  days. The default retention is 14 days.

The task payload currently carries collection options:

- `source_id`
- `range`: `7d`, `30d`, `90d`, `custom`, or `all`
- `start_date` / `end_date`: required when `range` is `custom`
- `limit`: `30`, `50`, `100`, or `0` for no limit
- `fetch_content`
- `skip_existing`
- `run_mode`

Stop behavior is cooperative. The API marks a `pending` or `running` task as
`cancelled`; the worker checks task status between page requests and article
writes, then exits the handler when cancellation is detected.

Delete behavior is limited to task records. Tasks can be deleted when their
status is `pending`, `failed`, `cancelled`, or `succeeded`; `running` tasks must
be stopped before deletion. Deleting a task does not delete collected articles.

For local debugging, the worker writes lifecycle logs to stdout:

- startup and poll interval
- no pending task found
- task acquired and task type
- task execution start, success, failure, or cancellation
- article list request page parameters
- returned item counts and saved article counts
- stop reasons such as reaching the limit, cutoff time, or last page

## Queue Evolution

PostgreSQL polling is enough for the MVP and local development. When collection
volume grows, the same task model can be moved behind a dedicated queue such as
Celery or Dramatiq with Redis:

- Keep `collection_tasks` as the durable task record and UI source of truth.
- Use Redis/Celery/Dramatiq for dispatching and concurrency control.
- Keep worker handlers idempotent so retries do not duplicate articles.
- Continue storing task timestamps, errors, and cancellation state in
PostgreSQL.

For WeChat-facing fetch work, keep concurrency conservative to reduce account
risk. Export workers can usually run with higher concurrency because they mostly
consume local stored content and CPU/IO.
