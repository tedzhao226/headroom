from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from headroom.models.monitor_sample import MonitorSample


@dataclass
class MonitorSampleRecord:
    endpoint: str
    usage_tps: int
    reserved_tokens: int
    available: int
    total_tps: int
    status: str
    consecutive_failures: int


class MonitorSampleRepository(Protocol):
    async def record(self, sample: MonitorSampleRecord) -> None: ...


class SqlAlchemyMonitorSampleRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, sample: MonitorSampleRecord) -> None:
        async with self._session_factory() as session:
            row = MonitorSample(
                endpoint=sample.endpoint,
                usage_tps=sample.usage_tps,
                reserved_tokens=sample.reserved_tokens,
                available=sample.available,
                total_tps=sample.total_tps,
                status=sample.status,
                consecutive_failures=sample.consecutive_failures,
            )
            session.add(row)
            await session.commit()
