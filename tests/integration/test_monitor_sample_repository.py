from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from headroom.models.monitor_sample import MonitorSample
from headroom.repository.monitor_samples import (
    MonitorSampleRecord,
    SqlAlchemyMonitorSampleRepository,
)

pytestmark = pytest.mark.asyncio


async def test_record_inserts_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SqlAlchemyMonitorSampleRepository(session_factory)
    sample = MonitorSampleRecord(
        endpoint="ep-a",
        usage_tps=1234,
        reserved_tokens=56,
        available=8710,
        total_tps=10_000,
        status="ok",
        consecutive_failures=0,
    )

    await repo.record(sample)

    async with session_factory() as session:
        rows = (await session.execute(
            select(MonitorSample).where(MonitorSample.endpoint == "ep-a")
        )).scalars().all()

    assert len(rows) >= 1
    row = rows[-1]
    assert row.usage_tps == 1234
    assert row.reserved_tokens == 56
    assert row.available == 8710
    assert row.total_tps == 10_000
    assert row.status == "ok"
    assert row.consecutive_failures == 0
    assert row.recorded_at is not None


async def test_record_stale_status_roundtrips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SqlAlchemyMonitorSampleRepository(session_factory)
    await repo.record(
        MonitorSampleRecord(
            endpoint="ep-stale",
            usage_tps=9000,
            reserved_tokens=0,
            available=1000,
            total_tps=10_000,
            status="stale",
            consecutive_failures=7,
        )
    )

    async with session_factory() as session:
        row = (await session.execute(
            select(MonitorSample).where(MonitorSample.endpoint == "ep-stale")
        )).scalar_one()

    assert row.status == "stale"
    assert row.consecutive_failures == 7
