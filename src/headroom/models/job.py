from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QueueType(str, enum.Enum):
    DAY = "day"
    NIGHT = "night"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    saq_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    queue: Mapped[QueueType] = mapped_column(
        Enum(QueueType, name="queue_type", values_callable=lambda e: [v.value for v in e]),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda e: [v.value for v in e]),
        nullable=False,
        default=JobStatus.PENDING,
    )

    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reschedule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_jobs_batch_id", "batch_id"),
        Index("ix_jobs_queue_status_created", "queue", "status", "created_at"),
    )
