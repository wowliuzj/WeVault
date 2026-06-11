"""create collection tasks

Revision ID: 20260610_0005
Revises: 20260610_0004
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260610_0005"
down_revision: str | None = "20260610_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

task_type = postgresql.ENUM(
    "fetch_source_articles",
    "fetch_article_content",
    "fetch_article_comments",
    "export_articles",
    name="task_type",
    create_type=False,
)
task_status = postgresql.ENUM(
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="task_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    task_type.create(bind, checkfirst=True)
    task_status.create(bind, checkfirst=True)

    op.create_table(
        "collection_tasks",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_collection_tasks_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_tasks")),
    )
    op.create_index(op.f("ix_collection_tasks_status"), "collection_tasks", ["status"])
    op.create_index(op.f("ix_collection_tasks_target_id"), "collection_tasks", ["target_id"])
    op.create_index(op.f("ix_collection_tasks_target_type"), "collection_tasks", ["target_type"])
    op.create_index(op.f("ix_collection_tasks_task_type"), "collection_tasks", ["task_type"])
    op.create_index(op.f("ix_collection_tasks_user_id"), "collection_tasks", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_collection_tasks_user_id"), table_name="collection_tasks")
    op.drop_index(op.f("ix_collection_tasks_task_type"), table_name="collection_tasks")
    op.drop_index(op.f("ix_collection_tasks_target_type"), table_name="collection_tasks")
    op.drop_index(op.f("ix_collection_tasks_target_id"), table_name="collection_tasks")
    op.drop_index(op.f("ix_collection_tasks_status"), table_name="collection_tasks")
    op.drop_table("collection_tasks")

    task_status.drop(op.get_bind(), checkfirst=True)
    task_type.drop(op.get_bind(), checkfirst=True)
