from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import TaskStatus, TaskType
from app.models.export import ExportFile, ExportJob
from app.models.task import CollectionTask


@dataclass
class ExportCleanupResult:
    cutoff: datetime
    deleted_jobs: int = 0
    deleted_files: int = 0
    deleted_tasks: int = 0
    deleted_dirs: int = 0


def export_job_dir(job: ExportJob) -> Path:
    return Path(settings.asset_storage_dir) / "exports" / str(job.user_id) / str(job.id)


def remove_empty_parents(path: Path, stop_at: Path) -> None:
    current = path
    stop_at = stop_at.resolve()
    while current.exists() and current.resolve() != stop_at:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


async def cleanup_expired_exports(db: AsyncSession) -> ExportCleanupResult:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, settings.export_file_ttl_days))
    result = ExportCleanupResult(cutoff=cutoff)

    job_result = await db.execute(
        select(ExportJob).where(
            ExportJob.status == TaskStatus.SUCCEEDED,
            ExportJob.finished_at.is_not(None),
            ExportJob.finished_at < cutoff,
        )
    )
    jobs = list(job_result.scalars().all())
    if not jobs:
        return result

    job_ids = [job.id for job in jobs]
    file_result = await db.execute(select(ExportFile).where(ExportFile.export_job_id.in_(job_ids)))
    files = list(file_result.scalars().all())

    storage_root = (Path(settings.asset_storage_dir) / "exports").resolve()
    for file in files:
        try:
            path = Path(file.file_path).resolve()
            if path.is_relative_to(storage_root):
                path.unlink(missing_ok=True)
                result.deleted_files += 1
        except OSError:
            continue

    for job in jobs:
        job_dir = export_job_dir(job)
        try:
            resolved = job_dir.resolve()
            if resolved.is_relative_to(storage_root) and resolved.exists():
                shutil.rmtree(resolved)
                result.deleted_dirs += 1
                remove_empty_parents(resolved.parent, storage_root)
        except OSError:
            continue

    task_delete = await db.execute(
        delete(CollectionTask).where(
            CollectionTask.task_type == TaskType.EXPORT_ARTICLES,
            CollectionTask.target_type == "export_job",
            CollectionTask.target_id.in_([UUID(str(job_id)) for job_id in job_ids]),
        )
    )
    result.deleted_tasks = int(task_delete.rowcount or 0)

    await db.execute(delete(ExportFile).where(ExportFile.export_job_id.in_(job_ids)))
    job_delete = await db.execute(delete(ExportJob).where(ExportJob.id.in_(job_ids)))
    result.deleted_jobs = int(job_delete.rowcount or len(job_ids))
    await db.commit()
    return result
