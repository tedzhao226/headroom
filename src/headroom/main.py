from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from saq.web.starlette import saq_web
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from headroom.api.health import router as health_router
from headroom.api.tasks import router as tasks_router
from headroom.core.config import Settings
from headroom.queue.setup import build_queues
from headroom.repository.jobs import SqlAlchemyJobRepository
from headroom.repository.monitor_samples import SqlAlchemyMonitorSampleRepository
from headroom.services.capacity_gate import InMemoryCapacityGate
from headroom.services.monitor import MockMonitor, VertexMonitor
from headroom.services.provider import MockProvider, VertexPTClient

logger = structlog.get_logger()


def create_app(*, settings: Settings | None = None, use_mocks: bool = False) -> FastAPI:
    settings = settings or Settings()
    day_queue, night_queue = build_queues(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        repo = SqlAlchemyJobRepository(session_factory)
        sample_repo = SqlAlchemyMonitorSampleRepository(session_factory)
        on_sample = sample_repo.record if settings.monitor_samples_enabled else None
        gates = {ep.name: InMemoryCapacityGate(ep.capacity_tps) for ep in settings.pt_endpoints}

        if use_mocks:
            provider = MockProvider()
            monitor = MockMonitor(
                gates=gates,
                scripts={ep.name: [(0, 0)] for ep in settings.pt_endpoints},
                tick_interval=5.0,
                capacities={ep.name: ep.capacity_tps for ep in settings.pt_endpoints},
                on_sample=on_sample,
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
                on_sample=on_sample,
            )

        app.state.settings = settings
        app.state.engine = engine
        app.state.repo = repo
        app.state.day_queue = day_queue
        app.state.night_queue = night_queue
        app.state.gates = gates
        app.state.provider = provider
        app.state.monitor = monitor
        app.state.monitor_task = asyncio.create_task(monitor.refresh_loop())

        await day_queue.connect()
        await night_queue.connect()

        logger.info("app_started", endpoints=list(gates.keys()))
        try:
            yield
        finally:
            monitor.stop()
            if app.state.monitor_task is not None:
                app.state.monitor_task.cancel()
            await day_queue.disconnect()
            await night_queue.disconnect()
            await engine.dispose()
            logger.info("app_stopped")

    app = FastAPI(title="headroom", lifespan=lifespan)
    app.include_router(tasks_router)
    app.include_router(health_router)
    app.mount("/monitor", saq_web("/monitor", queues=[day_queue, night_queue]))

    return app


def _default_app() -> FastAPI:
    import os

    use_mocks = os.environ.get("HEADROOM_USE_MOCKS", "").lower() in ("1", "true", "yes")
    return create_app(use_mocks=use_mocks)


app = _default_app()


def run() -> None:
    import uvicorn

    uvicorn.run("headroom.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
