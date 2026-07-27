from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.article import Article, ArticleContent
from app.models.enums import FetchStatus, SourceStatus, TaskStatus, TaskType
from app.models.export import ExportJob
from app.models.task import CollectionTask
from app.models.user import User
from app.models.wechat import WechatSource
from app.services.article_assets import cache_article_cover
from app.services.article_fetcher import fetch_article_content
from app.services.export_cleanup import cleanup_expired_exports
from app.services.exporter import run_export_job
from app.services.sources import (
    SourceServiceError,
    ensure_source_fakeid,
    get_active_authorized_session,
)
from app.services.wechat_login_driver import MP_BASE_URL, MP_HEADERS, wechat_login_manager


class TaskCancelled(RuntimeError):
    pass


QUEUE_TASK_TYPES: dict[str, tuple[TaskType, ...]] = {
    "fetch": (TaskType.FETCH_SOURCE_ARTICLES, TaskType.FETCH_ARTICLE_CONTENT),
    "export": (TaskType.EXPORT_ARTICLES,),
}


def log(message: str) -> None:
    print(f"[worker] {datetime.now(UTC).isoformat()} {message}", flush=True)


def task_types_for_queue(queue: str) -> Sequence[TaskType] | None:
    normalized = queue.strip().lower()
    if normalized in {"", "all", "*"}:
        return None
    if normalized not in QUEUE_TASK_TYPES:
        valid = ", ".join(["all", *QUEUE_TASK_TYPES])
        raise ValueError(f"Unsupported worker queue '{queue}'. Valid queues: {valid}.")
    return QUEUE_TASK_TYPES[normalized]


def auto_fetch_schedule_time() -> time:
    raw_value = settings.auto_fetch_schedule_time.strip()
    try:
        hour_text, minute_text = raw_value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("AUTO_FETCH_SCHEDULE_TIME must use HH:MM format.") from exc

    if hour not in range(24) or minute not in range(60):
        raise ValueError("AUTO_FETCH_SCHEDULE_TIME must be a valid local time.")
    return time(hour=hour, minute=minute)


async def acquire_pending_task(*, queue: str, worker_name: str) -> UUID | None:
    task_types = task_types_for_queue(queue)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            statement = (
                select(CollectionTask)
                .where(CollectionTask.status == TaskStatus.PENDING)
                .order_by(CollectionTask.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if task_types is not None:
                statement = statement.where(CollectionTask.task_type.in_(task_types))

            result = await db.execute(statement)
            task = result.scalar_one_or_none()
            if task is None:
                return None

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(UTC)
            task.finished_at = None
            task.error_message = None
            log(
                f"worker={worker_name} queue={queue} "
                f"acquired task={task.id} type={task.task_type.value}"
            )
            return task.id


async def run_task(task_id: UUID, *, worker_name: str) -> None:
    log(f"worker={worker_name} run task={task_id} started")
    try:
        async with AsyncSessionLocal() as db:
            task = await load_task(db, task_id)
            if task.task_type == TaskType.FETCH_SOURCE_ARTICLES:
                await fetch_source_articles(db, task)
            elif task.task_type == TaskType.FETCH_ARTICLE_CONTENT:
                await fetch_article_batch(db, task)
            elif task.task_type == TaskType.EXPORT_ARTICLES:
                await export_articles(db, task)
            else:
                raise RuntimeError(f"暂不支持的任务类型：{task.task_type.value}")

            await db.refresh(task)
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.SUCCEEDED
                task.finished_at = datetime.now(UTC)
                await db.commit()
                log(f"worker={worker_name} run task={task_id} succeeded")
    except TaskCancelled:
        log(f"worker={worker_name} run task={task_id} cancelled")
        return
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            task = await load_task(db, task_id)
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.FAILED
                task.error_message = str(exc) or "任务执行失败"
                task.finished_at = datetime.now(UTC)
                await sync_export_failure(db, task, task.error_message)
                await log_auto_fetch_auth_failure(db, task, exc)
                await db.commit()
                log(f"worker={worker_name} run task={task_id} failed error={task.error_message}")


async def load_task(db: AsyncSession, task_id: UUID) -> CollectionTask:
    result = await db.execute(select(CollectionTask).where(CollectionTask.id == task_id))
    task = result.scalar_one()
    return task


async def ensure_not_cancelled(db: AsyncSession, task: CollectionTask) -> None:
    await db.refresh(task)
    if task.status == TaskStatus.CANCELLED:
        log(f"task={task.id} cancellation detected")
        raise TaskCancelled()


def parse_payload_date(value: Any, *, end_of_day: bool = False) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed_date = datetime.fromisoformat(value).date()
    except ValueError:
        return None
    parsed_time = time.max if end_of_day else time.min
    return datetime.combine(parsed_date, parsed_time, tzinfo=UTC)


def task_date_bounds(payload: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    value = payload.get("range", "7d")
    if value == "custom":
        return (
            parse_payload_date(payload.get("start_date")),
            parse_payload_date(payload.get("end_date"), end_of_day=True),
        )
    days = {"7d": 7, "30d": 30, "90d": 90}.get(value)
    if days is None:
        return None, None
    return datetime.now(UTC) - timedelta(days=days), None


def normalize_article_item(item: dict[str, Any]) -> dict[str, Any]:
    create_time = item.get("create_time") or item.get("update_time")
    publish_time = None
    if isinstance(create_time, (int, float)) and create_time > 0:
        publish_time = datetime.fromtimestamp(create_time, tz=UTC)

    appmsgid = item.get("appmsgid") or item.get("app_msg_id") or item.get("aid")
    itemidx = item.get("itemidx") or item.get("item_idx") or item.get("idx") or 1

    return {
        "title": item.get("title") or "未命名文章",
        "author": item.get("author"),
        "digest": item.get("digest"),
        "cover_url": item.get("cover") or item.get("cover_url"),
        "original_url": item.get("link") or item.get("url"),
        "publish_time": publish_time,
        "msgid": str(item.get("comm_msg_info", {}).get("id") or item.get("msgid") or "")
        or None,
        "idx": int(itemidx) if str(itemidx).isdigit() else None,
        "appmsgid": str(appmsgid) if appmsgid else None,
        "itemidx": int(itemidx) if str(itemidx).isdigit() else None,
        "raw_data": item,
    }


async def fetch_source_articles(db: AsyncSession, task: CollectionTask) -> None:
    payload = task.payload or {}
    source_id = payload.get("source_id")
    if not source_id:
        raise RuntimeError("任务缺少 source_id。")

    source = await load_source(db, task.user_id, UUID(str(source_id)))
    user = await load_user(db, task.user_id)
    if not source.fakeid:
        log(f"task={task.id} source={source.id} missing fakeid, resolving from search")
        if not await ensure_source_fakeid(db, user, source):
            raise RuntimeError(
                "公众号源缺少 fakeid，且无法通过公众号名称自动补齐，请刷新公众号信息。"
            )
        await db.commit()
        await db.refresh(source)

    account, _, cookies, token = await get_active_authorized_session(db, user)
    log(
        "fetch_source_articles "
        f"task={task.id} source={source.id} name={source.name} "
        f"account={account.nickname} range={payload.get('range', '7d')} "
        f"start_date={payload.get('start_date')} end_date={payload.get('end_date')} "
        f"limit={int(payload.get('limit') or 0)} "
        f"fetch_content={bool(payload.get('fetch_content'))}"
    )
    headers = {**MP_HEADERS, "Cookie": wechat_login_manager._cookie_header(cookies)}
    start_at, end_at = task_date_bounds(payload)
    limit = int(payload.get("limit") or 0)
    skip_existing = bool(payload.get("skip_existing", True))
    fetch_content = bool(payload.get("fetch_content"))
    page_size = 5
    begin = 0
    saved_count = 0
    content_failures: list[str] = []

    task.progress_current = 0
    task.progress_total = limit
    await db.commit()

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        while True:
            await ensure_not_cancelled(db, task)
            if limit and saved_count >= limit:
                log(f"task={task.id} reached limit saved={saved_count}")
                break

            log(f"task={task.id} requesting article list begin={begin} count={page_size}")
            response = await client.get(
                f"{MP_BASE_URL}/cgi-bin/appmsg",
                params={
                    "action": "list_ex",
                    "begin": begin,
                    "count": page_size,
                    "fakeid": source.fakeid,
                    "type": "9",
                    "query": "",
                    "token": token,
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": "1",
                },
            )
            response.raise_for_status()
            data = response.json()
            base_resp = data.get("base_resp") or {}
            if base_resp.get("ret") not in (0, "0", None):
                raise RuntimeError(base_resp.get("err_msg") or "微信文章列表接口返回失败。")

            items = data.get("app_msg_list") or data.get("list") or []
            if not items:
                log(f"task={task.id} no more article items begin={begin}")
                break

            total = data.get("app_msg_cnt")
            if isinstance(total, int) and total > 0:
                task.progress_total = min(total, limit) if limit else total
            log(
                f"task={task.id} received items={len(items)} "
                f"total={task.progress_total} begin={begin}"
            )

            stop_for_cutoff = False
            for raw_item in items:
                await ensure_not_cancelled(db, task)
                article_data = normalize_article_item(raw_item)
                publish_time = article_data["publish_time"]
                if start_at and publish_time and publish_time < start_at:
                    stop_for_cutoff = True
                    continue
                if end_at and publish_time and publish_time > end_at:
                    continue
                if limit and saved_count >= limit:
                    break
                if not article_data["original_url"]:
                    continue

                article = await upsert_article(
                    db,
                    source,
                    account.id,
                    article_data,
                    skip_existing=skip_existing,
                    cookies=cookies,
                )
                saved_count += 1
                task.progress_current = saved_count
                await db.commit()
                log(
                    f"task={task.id} saved article={saved_count} "
                    f"title={article_data['title']}"
                )
                should_fetch_content = (
                    fetch_content
                    and article is not None
                    and article.content_status != FetchStatus.FETCHED
                )
                if should_fetch_content:
                    log(
                        f"task={task.id} auto fetching content "
                        f"article={article.id} title={article.title}"
                    )
                    try:
                        await fetch_article_content(db, article, cookies=cookies)
                        source.last_content_fetched_at = datetime.now(UTC)
                        await db.commit()
                        log(f"task={task.id} auto fetched content article={article.id}")
                    except Exception as exc:
                        content_failures.append(f"{article.title}: {exc}")
                        log(
                            f"task={task.id} auto fetch content failed "
                            f"article={article.id} error={exc}"
                        )

            source.last_list_fetched_at = datetime.now(UTC)
            await db.commit()

            if stop_for_cutoff or len(items) < page_size:
                reason = "cutoff" if stop_for_cutoff else "last_page"
                log(f"task={task.id} stopping list fetch reason={reason} saved={saved_count}")
                break
            begin += page_size
            await asyncio.sleep(0.4)

    if content_failures:
        raise RuntimeError("；".join(content_failures[:3]))


async def load_user(db: AsyncSession, user_id: UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


async def load_source(db: AsyncSession, user_id: UUID, source_id: UUID) -> WechatSource:
    result = await db.execute(
        select(WechatSource).where(
            WechatSource.id == source_id,
            WechatSource.user_id == user_id,
            WechatSource.deleted_at.is_(None),
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise RuntimeError("公众号源不存在。")
    return source


async def load_articles_by_ids(
    db: AsyncSession,
    user_id: UUID,
    article_ids: list[str],
) -> list[Article]:
    ids = [UUID(str(article_id)) for article_id in article_ids]
    result = await db.execute(
        select(Article).where(
            Article.user_id == user_id,
            Article.id.in_(ids),
        )
    )
    articles = list(result.scalars().all())
    if len(articles) != len(set(ids)):
        raise RuntimeError("部分文章不存在。")
    article_by_id = {article.id: article for article in articles}
    return [article_by_id[article_id] for article_id in ids]


async def load_task_articles(db: AsyncSession, task: CollectionTask) -> list[Article]:
    payload = task.payload or {}
    article_ids = payload.get("article_ids")
    if not isinstance(article_ids, list) or not article_ids:
        raise RuntimeError("任务缺少 article_ids。")
    return await load_articles_by_ids(
        db,
        task.user_id,
        [str(article_id) for article_id in article_ids],
    )


async def fetch_article_batch(
    db: AsyncSession,
    task: CollectionTask,
) -> None:
    user = await load_user(db, task.user_id)
    try:
        _, _, cookies, _ = await get_active_authorized_session(db, user)
    except Exception as exc:
        log(f"task={task.id} content fetch continuing without authorization error={exc}")
        cookies = None

    articles = await load_task_articles(db, task)
    task.progress_current = 0
    task.progress_total = len(articles)
    await db.commit()

    failures: list[str] = []
    for index, article in enumerate(articles, start=1):
        await ensure_not_cancelled(db, task)
        log(f"task={task.id} fetching content article={article.id} title={article.title}")
        try:
            await fetch_article_content(db, article, cookies=cookies)
            log(f"task={task.id} fetched content article={article.id}")
        except Exception as exc:
            failures.append(f"{article.title}: {exc}")
            log(f"task={task.id} fetch content failed article={article.id} error={exc}")

        task.progress_current = index
        await db.commit()

    if failures:
        raise RuntimeError("；".join(failures[:3]))


async def load_export_job(db: AsyncSession, task: CollectionTask) -> ExportJob:
    payload = task.payload or {}
    export_job_id = payload.get("export_job_id")
    if not export_job_id:
        raise RuntimeError("任务缺少 export_job_id。")

    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == UUID(str(export_job_id)),
            ExportJob.user_id == task.user_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise RuntimeError("导出任务不存在。")
    return job


async def export_articles(db: AsyncSession, task: CollectionTask) -> None:
    job = await load_export_job(db, task)
    user = await load_user(db, task.user_id)
    try:
        _, _, cookies, _ = await get_active_authorized_session(db, user)
    except Exception as exc:
        log(f"task={task.id} export continuing without authorization error={exc}")
        cookies = None

    job.status = TaskStatus.RUNNING
    task.progress_current = 0
    task.progress_total = len(job.article_ids)
    await db.commit()
    log(
        f"task={task.id} exporting job={job.id} name={job.name} "
        f"format={job.format.value} articles={len(job.article_ids)}"
    )
    articles = await load_articles_by_ids(db, task.user_id, job.article_ids)
    for index, article in enumerate(articles, start=1):
        await ensure_not_cancelled(db, task)
        if article.content_status != FetchStatus.FETCHED:
            log(f"task={task.id} export prefetch article={article.id} title={article.title}")
            await fetch_article_content(db, article, cookies=cookies)
        else:
            content_result = await db.execute(
                select(ArticleContent).where(ArticleContent.article_id == article.id)
            )
            if content_result.scalar_one_or_none() is None:
                log(f"task={task.id} export refetch missing content article={article.id}")
                await fetch_article_content(db, article, cookies=cookies)
        task.progress_current = index
        await db.commit()

    await run_export_job(db, job)
    task.progress_current = task.progress_total
    await db.commit()
    log(f"task={task.id} exported job={job.id}")


async def sync_export_failure(
    db: AsyncSession,
    task: CollectionTask,
    error_message: str,
) -> None:
    if task.task_type != TaskType.EXPORT_ARTICLES:
        return
    try:
        job = await load_export_job(db, task)
    except Exception:
        return
    job.status = TaskStatus.FAILED
    job.error_message = error_message
    job.finished_at = datetime.now(UTC)


async def log_auto_fetch_auth_failure(
    db: AsyncSession,
    task: CollectionTask,
    exc: Exception,
) -> None:
    payload = task.payload or {}
    if payload.get("trigger") != "auto":
        return
    if task.task_type != TaskType.FETCH_SOURCE_ARTICLES:
        return
    if not isinstance(exc, SourceServiceError) and not _looks_like_auth_failure(str(exc)):
        return
    source_id = payload.get("source_id")
    if not source_id:
        return

    result = await db.execute(
        select(WechatSource).where(
            WechatSource.id == UUID(str(source_id)),
            WechatSource.user_id == task.user_id,
            WechatSource.deleted_at.is_(None),
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        return
    if isinstance(exc, SourceServiceError) and not _looks_like_auth_failure(str(exc)):
        return
    log(f"task={task.id} auto fetch auth failed source={source.id} reason={exc}")


def _looks_like_auth_failure(message: str) -> bool:
    text = message.lower()
    return any(
        keyword in text
        for keyword in (
            "授权",
            "token",
            "cookie",
            "登录态",
            "扫码",
            "session",
            "invalid",
            "expired",
            "过期",
        )
    )


async def upsert_article(
    db: AsyncSession,
    source: WechatSource,
    wechat_account_id: UUID,
    article_data: dict[str, Any],
    *,
    skip_existing: bool,
    cookies: list[dict[str, Any]] | None,
) -> Article | None:
    article = None
    if article_data["appmsgid"] and article_data["itemidx"] is not None:
        result = await db.execute(
            select(Article).where(
                Article.source_id == source.id,
                Article.appmsgid == article_data["appmsgid"],
                Article.itemidx == article_data["itemidx"],
            )
        )
        article = result.scalar_one_or_none()

    if article is not None and article.deleted_at is not None:
        log(f"skip deleted article source={source.id} appmsgid={article.appmsgid}")
        return None

    if article is not None and skip_existing:
        if article.cover_url and not article.cover_storage_path:
            cached = await cache_article_cover(article, cookies=cookies)
            if not cached:
                log(f"cover cache failed article={article.id} title={article.title}")
        return article

    if article is None:
        article = Article(
            user_id=source.user_id,
            source_id=source.id,
            wechat_account_id=wechat_account_id,
            title=article_data["title"],
            author=article_data["author"],
            digest=article_data["digest"],
            cover_url=article_data["cover_url"],
            original_url=article_data["original_url"],
            publish_time=article_data["publish_time"],
            msgid=article_data["msgid"],
            idx=article_data["idx"],
            biz=source.biz,
            appmsgid=article_data["appmsgid"],
            itemidx=article_data["itemidx"],
            content_status=FetchStatus.PENDING,
            raw_data=article_data["raw_data"],
        )
        db.add(article)
        await db.flush()
        cached = await cache_article_cover(article, cookies=cookies)
        if not cached:
            log(f"cover cache failed article={article.id} title={article.title}")
        return article

    article.title = article_data["title"]
    article.author = article_data["author"]
    article.digest = article_data["digest"]
    article.cover_url = article_data["cover_url"]
    article.original_url = article_data["original_url"]
    article.publish_time = article_data["publish_time"]
    article.msgid = article_data["msgid"]
    article.idx = article_data["idx"]
    article.raw_data = article_data["raw_data"]
    cached = await cache_article_cover(article, cookies=cookies)
    if not cached:
        log(f"cover cache failed article={article.id} title={article.title}")
    return article


async def run_worker_slot(worker_name: str, *, poll_interval: float, queue: str) -> None:
    idle_count = 0
    while True:
        task_id = await acquire_pending_task(queue=queue, worker_name=worker_name)
        if task_id is None:
            idle_count += 1
            if idle_count == 1 or idle_count % 30 == 0:
                log(f"worker={worker_name} queue={queue} no pending task")
            await asyncio.sleep(poll_interval)
            continue

        idle_count = 0
        await run_task(task_id, worker_name=worker_name)


async def run_export_cleanup_loop() -> None:
    interval = max(60, settings.export_cleanup_interval_seconds)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await cleanup_expired_exports(db)
            log(
                "export cleanup "
                f"cutoff={result.cutoff.isoformat()} "
                f"deleted_jobs={result.deleted_jobs} "
                f"deleted_files={result.deleted_files} "
                f"deleted_tasks={result.deleted_tasks} "
                f"deleted_dirs={result.deleted_dirs}"
            )
        except Exception as exc:
            log(f"export cleanup failed error={exc}")
        await asyncio.sleep(interval)


async def schedule_auto_fetch_sources() -> int:
    now = datetime.now().astimezone()
    lookback_days = max(0, settings.auto_fetch_lookback_days)
    scheduled_count = 0
    changed_count = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WechatSource)
            .where(
                WechatSource.status == SourceStatus.ACTIVE,
                WechatSource.auto_fetch_enabled.is_(True),
                WechatSource.deleted_at.is_(None),
            )
            .order_by(WechatSource.updated_at.asc())
        )
        sources = list(result.scalars().all())
        for source in sources:
            user = await load_user(db, source.user_id)
            try:
                await get_active_authorized_session(db, user)
            except SourceServiceError as exc:
                log(f"auto fetch skipped source={source.id} reason={exc}")
                continue

            if source.auto_fetch_last_scheduled_at is not None:
                last_scheduled_date = source.auto_fetch_last_scheduled_at.astimezone().date()
                if last_scheduled_date >= now.date():
                    continue

            pending_result = await db.execute(
                select(CollectionTask.id)
                .where(
                    CollectionTask.user_id == source.user_id,
                    CollectionTask.task_type == TaskType.FETCH_SOURCE_ARTICLES,
                    CollectionTask.target_type == "wechat_source",
                    CollectionTask.target_id == source.id,
                    CollectionTask.status.in_((TaskStatus.PENDING, TaskStatus.RUNNING)),
                )
                .limit(1)
            )
            if pending_result.scalar_one_or_none() is not None:
                source.auto_fetch_last_scheduled_at = now
                changed_count += 1
                continue

            db.add(
                CollectionTask(
                    user_id=source.user_id,
                    task_type=TaskType.FETCH_SOURCE_ARTICLES,
                    status=TaskStatus.PENDING,
                    progress_current=0,
                    progress_total=0,
                    retry_count=0,
                    target_type="wechat_source",
                    target_id=source.id,
                    payload={
                        "source_id": str(source.id),
                        "range": "custom",
                        "start_date": (now.date() - timedelta(days=lookback_days)).isoformat(),
                        "end_date": now.date().isoformat(),
                        "limit": 0,
                        "fetch_content": source.auto_fetch_content,
                        "skip_existing": True,
                        "run_mode": "immediate",
                        "trigger": "auto",
                    },
                )
            )
            source.auto_fetch_last_scheduled_at = now
            scheduled_count += 1
            changed_count += 1

        if changed_count:
            await db.commit()
    return scheduled_count


async def run_auto_fetch_scheduler_loop() -> None:
    schedule_time = auto_fetch_schedule_time()
    log(f"auto fetch scheduler schedule_time={schedule_time.strftime('%H:%M')}")
    while True:
        now = datetime.now().astimezone()
        today_schedule = datetime.combine(now.date(), schedule_time, tzinfo=now.tzinfo)
        if now >= today_schedule:
            try:
                scheduled_count = await schedule_auto_fetch_sources()
                if scheduled_count:
                    log(f"auto fetch scheduled tasks={scheduled_count}")
            except Exception as exc:
                log(f"auto fetch scheduler failed error={exc}")

        next_check = today_schedule
        if now >= next_check:
            next_check += timedelta(days=1)
        await asyncio.sleep(max(60.0, (next_check - now).total_seconds()))


async def run_worker_loop(
    poll_interval: float,
    *,
    concurrency: int = 1,
    queue: str = "all",
) -> None:
    task_types_for_queue(queue)
    worker_count = max(1, concurrency)
    log(f"starting queue={queue} concurrency={worker_count} poll_interval={poll_interval}s")
    slots = [
        asyncio.create_task(
            run_worker_slot(
                f"{queue}-{slot}",
                poll_interval=poll_interval,
                queue=queue,
            )
        )
        for slot in range(1, worker_count + 1)
    ]
    slots.append(asyncio.create_task(run_export_cleanup_loop()))
    if queue in {"all", "fetch"}:
        slots.append(asyncio.create_task(run_auto_fetch_scheduler_loop()))
    await asyncio.gather(*slots)
