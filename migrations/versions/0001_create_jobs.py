"""create jobs table

Revision ID: 0001
Revises:
Create Date: 2026-04-17

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("saq_job_id", sa.String(128), nullable=True),
        sa.Column(
            "queue",
            sa.Enum("day", "night", name="queue_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "complete",
                "failed",
                "cancelled",
                name="job_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("request", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("estimated_tokens", sa.Integer, nullable=False),
        sa.Column("actual_tokens", sa.Integer, nullable=True),
        sa.Column("reschedule_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])
    op.create_index(
        "ix_jobs_queue_status_created",
        "jobs",
        ["queue", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_queue_status_created", table_name="jobs")
    op.drop_index("ix_jobs_batch_id", table_name="jobs")
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS queue_type")
