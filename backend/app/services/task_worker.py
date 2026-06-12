from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.article import Article
from app.models.enums import FetchStatus, TaskStatus, TaskType
from app.models.task import CollectionTask
from app.models.user import User
from app.models.wechat import WechatSource
from app.services.article_assets import cache_article_cover
from app.services.article_fetcher import fetch_article_content
from app.services.sources import get_active_authorized_session
from app.services.wechat_login_driver import MP_BASE_URL, MP_HEADERS, wechat_login_manager


class TaskCancelled(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[worker] {datetime.now(UTC).isoformat()} {message}", flush=True)


async def acquire_pending_task() -> UUID | None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(CollectionTask)
                .where(CollectionTask.status == TaskStatus.PENDING)
                .order_by(CollectionTask.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            task = result.scalar_one_or_none()
            if task is None:
                log("no pending task")
                return None

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(UTC)
            task.finished_at = None
            task.error_message = None
            log(f"acquired task={task.id} type={task.task_type.value}")
            return task.id


async def run_task(task_id: UUID) -> None:
    log(f"run task={task_id} started")
    try:
        async with AsyncSessionLocal() as db:
            task = await load_task(db, task_id)
            if task.task_type == TaskType.FETCH_SOURCE_ARTICLES:
                await fetch_source_articles(db, task)
            elif task.task_type == TaskType.FETCH_ARTICLE_CONTENT:
                await fetch_article_batch(db, task)
            else:
                raise RuntimeError(f"暂不支持的任务类型：{task.task_type.value}")

            await db.refresh(task)
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.SUCCEEDED
                task.finished_at = datetime.now(UTC)
                await db.commit()
                log(f"run task={task_id} succeeded")
    except TaskCancelled:
        log(f"run task={task_id} cancelled")
        return
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            task = await load_task(db, task_id)
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.FAILED
                task.error_message = str(exc) or "任务执行失败"
                task.finished_at = datetime.now(UTC)
                await db.commit()
                log(f"run task={task_id} failed error={task.error_message}")


async def load_task(db: AsyncSession, task_id: UUID) -> CollectionTask:
    result = await db.execute(select(CollectionTask).where(CollectionTask.id == task_id))
    task = result.scalar_one()
    return task


async def ensure_not_cancelled(db: AsyncSession, task: CollectionTask) -> None:
    await db.refresh(task)
    if task.status == TaskStatus.CANCELLED:
        log(f"task={task.id} cancellation detected")
        raise TaskCancelled()


def task_cutoff(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("range", "7d")
    days = {"7d": 7, "30d": 30, "90d": 90}.get(value)
    if days is None:
        return None
    return datetime.now(UTC) - timedelta(days=days)


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
    if not source.fakeid:
        raise RuntimeError("公众号源缺少 fakeid，请先刷新公众号信息。")

    user = await load_user(db, task.user_id)
    account, _, cookies, token = await get_active_authorized_session(db, user)
    log(
        "fetch_source_articles "
        f"task={task.id} source={source.id} name={source.name} "
        f"account={account.nickname} range={payload.get('range', '7d')} "
        f"limit={int(payload.get('limit') or 0)} "
        f"fetch_content={bool(payload.get('fetch_content'))}"
    )
    headers = {**MP_HEADERS, "Cookie": wechat_login_manager._cookie_header(cookies)}
    cutoff = task_cutoff(payload)
    limit = int(payload.get("limit") or 0)
    skip_existing = bool(payload.get("skip_existing", True))
    page_size = 5
    begin = 0
    saved_count = 0

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
                if cutoff and publish_time and publish_time < cutoff:
                    stop_for_cutoff = True
                    continue
                if limit and saved_count >= limit:
                    break
                if not article_data["original_url"]:
                    continue

                await upsert_article(
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

            source.last_list_fetched_at = datetime.now(UTC)
            await db.commit()

            if stop_for_cutoff or len(items) < page_size:
                reason = "cutoff" if stop_for_cutoff else "last_page"
                log(f"task={task.id} stopping list fetch reason={reason} saved={saved_count}")
                break
            begin += page_size
            await asyncio.sleep(0.4)


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


async def load_task_articles(db: AsyncSession, task: CollectionTask) -> list[Article]:
    payload = task.payload or {}
    article_ids = payload.get("article_ids")
    if not isinstance(article_ids, list) or not article_ids:
        raise RuntimeError("任务缺少 article_ids。")

    ids = [UUID(str(article_id)) for article_id in article_ids]
    result = await db.execute(
        select(Article).where(
            Article.user_id == task.user_id,
            Article.id.in_(ids),
        )
    )
    articles = list(result.scalars().all())
    if len(articles) != len(set(ids)):
        raise RuntimeError("部分文章不存在。")
    article_by_id = {article.id: article for article in articles}
    return [article_by_id[article_id] for article_id in ids]


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


async def upsert_article(
    db: AsyncSession,
    source: WechatSource,
    wechat_account_id: UUID,
    article_data: dict[str, Any],
    *,
    skip_existing: bool,
    cookies: list[dict[str, Any]] | None,
) -> None:
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
        return

    if article is not None and skip_existing:
        if article.cover_url and not article.cover_storage_path:
            cached = await cache_article_cover(article, cookies=cookies)
            if not cached:
                log(f"cover cache failed article={article.id} title={article.title}")
        return

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
            comment_status=FetchStatus.PENDING,
            raw_data=article_data["raw_data"],
        )
        db.add(article)
        await db.flush()
        cached = await cache_article_cover(article, cookies=cookies)
        if not cached:
            log(f"cover cache failed article={article.id} title={article.title}")
        return

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


async def run_worker_loop(poll_interval: float) -> None:
    while True:
        task_id = await acquire_pending_task()
        if task_id is None:
            await asyncio.sleep(poll_interval)
            continue

        await run_task(task_id)
