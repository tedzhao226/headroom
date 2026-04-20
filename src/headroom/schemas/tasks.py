from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from headroom.models.job import JobStatus, QueueType


class TaskSubmit(BaseModel):
    queue: QueueType
    model: str
    messages: list[dict]
    parameters: dict = Field(default_factory=dict)
    estimated_tokens: int = Field(gt=0)
    endpoint: str | None = None  # required only if multiple endpoints share a model


class TaskResponse(BaseModel):
    id: UUID
    batch_id: UUID | None
    queue: QueueType
    status: JobStatus
    endpoint: str
    estimated_tokens: int
    actual_tokens: int | None
    result: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
