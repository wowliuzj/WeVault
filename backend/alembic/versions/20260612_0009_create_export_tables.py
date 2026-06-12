"""create export tables

Revision ID: 20260612_0009
Revises: 20260610_0008
Create Date: 2026-06-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260612_0009"
down_revision: str | None = "20260610_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

export_format = postgresql.ENUM(
    "pdf",
    "docx",
    "markdown",
    "zip",
    name="export_format",
    create_type=False,
)
export_status = postgresql.ENUM(
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="export_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    export_format.create(bind, checkfirst=True)
    export_status.create(bind, checkfirst=True)
    op.create_table(
        "export_jobs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("format", export_format, nullable=False),
        sa.Column("status", export_status, nullable=False),
        sa.Column("article_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_export_jobs_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_jobs")),
    )
    op.create_index(op.f("ix_export_jobs_user_id"), "export_jobs", ["user_id"])
    op.create_index(op.f("ix_export_jobs_status"), "export_jobs", ["status"])
    op.create_table(
        "export_files",
        sa.Column("export_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["export_job_id"],
            ["export_jobs.id"],
            name=op.f("fk_export_files_export_job_id_export_jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_files")),
    )
    op.create_index(op.f("ix_export_files_export_job_id"), "export_files", ["export_job_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_export_files_export_job_id"), table_name="export_files")
    op.drop_table("export_files")
    op.drop_index(op.f("ix_export_jobs_status"), table_name="export_jobs")
    op.drop_index(op.f("ix_export_jobs_user_id"), table_name="export_jobs")
    op.drop_table("export_jobs")
    export_status.drop(op.get_bind(), checkfirst=True)
    export_format.drop(op.get_bind(), checkfirst=True)
