from __future__ import annotations

import asyncio
import sys

import structlog
from saq import Worker
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from headroom.core.config import Settings
from headroom.queue.hooks import after_process, before_process
from headroom.queue.setup import build_queues
from headroom.queue.tasks import run_task
from headroom.repository.jobs import SqlAlchemyJobRepository
from headroom.services.capacity_gate import InMemoryCapacityGate
from headroom.services.monitor import MockMonitor, VertexMonitor
from headroom.services.provider import MockProvider, VertexPTClient

logger = structlog.get_logger()


async def _run(queue_name: str, *, use_mocks: bool = False) -> None:
    settings = Settings()
    day_queue, night_queue = build_queues(settings.database_url)
    queue = {"day": day_queue, "night": night_queue}[queue_name]

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyJobRepository(session_factory)

    gates = {ep.name: InMemoryCapacityGate(ep.capacity_tps) for ep in settings.pt_endpoints}

    if use_mocks:
        provider = MockProvider()
        monitor = MockMonitor(
            gates=gates,
            scripts={ep.name: [(0, 0)] for ep in settings.pt_endpoints},
            tick_interval=5.0,
        )
    else:
        from headroom.core.credentials import get_gcp_credentials

        credentials = get_gcp_credentials()
        provider = VertexPTClient(
            project=settings.gcp_project,
            region=settings.pt_endpoints[0].region,
            credentials=credentials,
            num_retries=settings.pt_num_retries,
        )
        monitor = VertexMonitor(
            gates=gates,
            project=settings.gcp_project,
            endpoint_configs=settings.pt_endpoints,
            credentials=credentials,
            interval=settings.pt_monitor_interval,
            failure_threshold=settings.pt_monitor_failure_threshold,
        )

    concurrency = (
        settings.day_queue_concurrency if queue_name == "day" else settings.night_queue_concurrency
    )

    async def startup(ctx: dict) -> None:
        ctx["settings"] = settings
        ctx["repo"] = repo
        ctx["gates"] = gates
        ctx["provider"] = provider
        ctx["day_queue"] = day_queue
        ctx["night_queue"] = night_queue
        ctx["monitor_task"] = asyncio.create_task(monitor.refresh_loop())
        logger.info("worker_started", queue=queue_name, concurrency=concurrency)

    async def shutdown(ctx: dict) -> None:
        monitor.stop()
        task = ctx.get("monitor_task")
        if task is not None:
            task.cancel()
        await engine.dispose()
        logger.info("worker_stopped", queue=queue_name)

    worker = Worker(
        queue=queue,
        functions=[run_task],
        concurrency=concurrency,
        startup=startup,
        shutdown=shutdown,
        before_process=before_process,
        after_process=after_process,
    )
    await queue.connect()
    try:
        await worker.start()
    finally:
        await queue.disconnect()


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("day", "night"):
        print("usage: headroom-worker {day|night} [--mock]", file=sys.stderr)
        raise SystemExit(2)
    use_mocks = "--mock" in sys.argv[2:]
    asyncio.run(_run(sys.argv[1], use_mocks=use_mocks))


if __name__ == "__main__":
    main()
