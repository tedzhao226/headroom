from __future__ import annotations

from saq.queue.postgres import PostgresQueue


def _saq_url(database_url: str) -> str:
    """SAQ expects a psycopg-compatible url; strip the asyncpg driver suffix."""
    return database_url.replace("postgresql+asyncpg", "postgresql")


def build_queues(database_url: str) -> tuple[PostgresQueue, PostgresQueue]:
    """Build (day, night) queues sharing the same Postgres."""
    saq_url = _saq_url(database_url)
    day = PostgresQueue.from_url(saq_url, name="day")
    night = PostgresQueue.from_url(saq_url, name="night")
    return day, night
