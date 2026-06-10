# WeVault

WeVault is a WeChat Official Account content vault for collecting, preserving, and exporting articles and comments.

The first version focuses on a small, reliable loop:

- Multi-user platform login
- WeChat Official Account authorization
- Public account source management
- Article list collection
- Selected article content collection
- Article comment collection
- Long-term storage of HTML, Markdown, plain text, assets, and comments
- Text-preserving export to PDF, DOCX, and Markdown

## Project Structure

```text
WeVault/
  backend/   FastAPI service, workers, crawlers, exporters
  frontend/  Vue 3 management UI
  docs/      Product and architecture design documents
```

## Planned Stack

- Frontend: Vue 3, TypeScript, Vite, Naive UI
- Backend: FastAPI, SQLAlchemy 2.x, Alembic
- Database: PostgreSQL
- Queue/cache: Redis with Celery or Dramatiq
- Browser automation: Playwright Chromium
- Export: Chromium PDF, DOCX generator, Markdown package

## MVP Scope

Version 1 intentionally skips workspace collaboration, NotebookLM integration, and AI analysis. Those features can be added after the collection, storage, and export pipeline is stable.

