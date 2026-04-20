"""create monitor_samples table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_samples",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("usage_tps", sa.Integer, nullable=False),
        sa.Column("reserved_tokens", sa.Integer, nullable=False),
        sa.Column("available", sa.Integer, nullable=False),
        sa.Column("total_tps", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_monitor_samples_endpoint_recorded_at",
        "monitor_samples",
        ["endpoint", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monitor_samples_endpoint_recorded_at", table_name="monitor_samples"
    )
    op.drop_table("monitor_samples")
