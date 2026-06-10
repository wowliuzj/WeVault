# WeVault Architecture Draft

## Product Goal

WeVault is a personal and team-ready archive for WeChat Official Account content. It turns public account article streams into a durable knowledge base with clean text, comments, assets, and high-quality exports.

## First Version Scope

The MVP should include:

- Platform user login
- One active WeChat authorization per user, while keeping the data model ready for multiple authorizations
- Public account source discovery by account search or article URL parsing
- Article list synchronization after a source is added
- Manual article content collection from selected articles
- Optional source-level automatic content and comment collection
- Article comment collection
- Article library with collection status
- Export center for PDF, DOCX, and Markdown

The MVP should not include:

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
  Comment collection
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
  -> Worker fetches article HTML, assets, text, Markdown, and comments
  -> User exports selected articles as PDF, DOCX, or Markdown
```

## Collection Strategy

Public account sources should support two discovery methods:

- Search by public account name
- Parse from an existing article URL

After a source is added, WeVault should fetch the article list first. Full article content and comments should be separate tasks. Each source can define whether content and comments should be fetched automatically after list synchronization.

Recommended source settings:

- `auto_fetch_content`
- `auto_fetch_comments`
- `fetch_limit_per_run`
- `fetch_since_days`
- `comment_fetch_policy`

Default behavior should be conservative:

- Fetch article list automatically
- Do not fetch article content automatically
- Do not fetch comments automatically

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
- `article_comments`
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
- `fetch_article_comments`
- `export_articles`

Tasks should record status, progress, retry count, error message, and timestamps.

Recommended statuses:

- `pending`
- `running`
- `succeeded`
- `failed`
- `cancelled`

