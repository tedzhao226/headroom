from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from headroom.models.job import JobStatus, QueueType
from headroom.repository.jobs import SqlAlchemyJobRepository


async def test_create_persists_job(repo: SqlAlchemyJobRepository) -> None:
    job = await repo.create(
        queue=QueueType.DAY,
        endpoint="flash-us",
        request={"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "hi"}]},
        estimated_tokens=500,
    )
    assert job.id is not None
    assert job.status is JobStatus.PENDING
    assert job.created_at is not None


async def test_get_returns_created_job(repo: SqlAlchemyJobRepository) -> None:
    job = await repo.create(
        queue=QueueType.DAY,
        endpoint="flash-us",
        request={"model": "gemini-2.5-flash", "messages": []},
        estimated_tokens=100,
    )
    fetched = await repo.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.endpoint == "flash-us"


async def test_get_missing_returns_none(repo: SqlAlchemyJobRepository) -> None:
    assert await repo.get(uuid.uuid4()) is None


async def test_update_status_transitions(repo: SqlAlchemyJobRepository) -> None:
    job = await repo.create(
        queue=QueueType.DAY,
        endpoint="flash-us",
        request={"model": "gemini-2.5-flash", "messages": []},
        estimated_tokens=100,
    )
    now = datetime.now(timezone.utc)
    await repo.update_status(job.id, JobStatus.RUNNING, started_at=now, saq_job_id="saq-1")
    mid = await repo.get(job.id)
    assert mid is not None
    assert mid.status is JobStatus.RUNNING
    assert mid.saq_job_id == "saq-1"

    await repo.update_status(
        job.id,
        JobStatus.COMPLETE,
        result={"output": "ok", "actual_token_count": 150},
        actual_tokens=150,
        completed_at=now,
    )
    final = await repo.get(job.id)
    assert final is not None
    assert final.status is JobStatus.COMPLETE
    assert final.actual_tokens == 150
    assert final.result == {"output": "ok", "actual_token_count": 150}


async def test_update_status_unknown_raises(repo: SqlAlchemyJobRepository) -> None:
    with pytest.raises(LookupError):
        await repo.update_status(uuid.uuid4(), JobStatus.FAILED, error="gone")


async def test_get_by_batch(repo: SqlAlchemyJobRepository) -> None:
    batch_id = uuid.uuid4()
    for _ in range(3):
        await repo.create(
            queue=QueueType.DAY,
            endpoint="flash-us",
            request={"model": "gemini-2.5-flash", "messages": []},
            estimated_tokens=100,
            batch_id=batch_id,
        )
    rows = await repo.get_by_batch(batch_id)
    assert len(rows) == 3
    assert all(r.batch_id == batch_id for r in rows)
