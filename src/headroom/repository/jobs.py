from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from headroom.models.job import Job, JobStatus, QueueType


class JobRepository(Protocol):
    async def create(
        self,
        *,
        queue: QueueType,
        endpoint: str,
        request: dict,
        estimated_tokens: int,
        batch_id: UUID | None = None,
    ) -> Job: ...

    async def get(self, job_id: UUID) -> Job | None: ...

    async def get_by_batch(self, batch_id: UUID) -> list[Job]: ...

    async def update_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        result: dict | None = None,
        actual_tokens: int | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        saq_job_id: str | None = None,
    ) -> None: ...


class SqlAlchemyJobRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        queue: QueueType,
        endpoint: str,
        request: dict,
        estimated_tokens: int,
        batch_id: UUID | None = None,
    ) -> Job:
        async with self._session_factory() as session:
            job = Job(
                queue=queue,
                endpoint=endpoint,
                request=request,
                estimated_tokens=estimated_tokens,
                batch_id=batch_id,
                status=JobStatus.PENDING,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def get(self, job_id: UUID) -> Job | None:
        async with self._session_factory() as session:
            return await session.get(Job, job_id)

    async def get_by_batch(self, batch_id: UUID) -> list[Job]:
        async with self._session_factory() as session:
            rows = await session.execute(select(Job).where(Job.batch_id == batch_id))
            return list(rows.scalars().all())

    async def update_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        result: dict | None = None,
        actual_tokens: int | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        saq_job_id: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise LookupError(f"job {job_id} not found")
            job.status = status
            if result is not None:
                job.result = result
            if actual_tokens is not None:
                job.actual_tokens = actual_tokens
            if error is not None:
                job.error = error
            if started_at is not None:
                job.started_at = started_at
            if completed_at is not None:
                job.completed_at = completed_at
            if saq_job_id is not None:
                job.saq_job_id = saq_job_id
            await session.commit()
