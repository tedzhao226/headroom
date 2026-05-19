# Tasks: headroom MVP

**Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

Tasks are grouped by module.
This file is a current snapshot of implemented work and known missing tests.

## T1. Core config and credentials
- [x] T1.1 `src/headroom/core/config.py` — `EndpointConfig`, `Settings` with TOML source.
- [x] T1.2 `src/headroom/core/credentials.py` — `get_gcp_credentials()` from `GCP_SA_KEY`.
- [x] T1.3 `src/headroom/core/time_window.py` — `is_within_window(now, start, end)`, `next_window_start_utc(start)`.
- [x] T1.4 Tests: `tests/unit/test_config.py`, `test_credentials.py`, `test_time_window.py`.

## T2. Services (port from pt_headroom)
- [x] T2.1 `services/capacity_gate.py` — `CapacityGate` Protocol, `InMemoryCapacityGate`.
- [x] T2.2 `services/monitor.py` — `Monitor` Protocol, `VertexMonitor`, `MockMonitor`.
- [x] T2.3 `services/provider.py` — `Provider` Protocol, `VertexPTClient`, `MockProvider`.
- [x] T2.4 Tests: `tests/unit/test_capacity_gate.py`, `test_monitor.py`, `test_provider.py`.

## T3. Persistence
- [x] T3.1 `models/job.py` — SQLAlchemy `Job` + `QueueType`, `JobStatus` enums.
- [x] T3.2 `alembic.ini` + `migrations/env.py` + `migrations/versions/0001_create_jobs.py`.
- [x] T3.3 `repository/jobs.py` — `JobRepository` Protocol + SQLAlchemy impl.
- [x] T3.4 Integration test: `tests/integration/test_repository.py` (testcontainers pg).
- [x] T3.5 `monitor_samples` model, repository, migration, and integration tests.

## T4. Queue
- [x] T4.1 `queue/setup.py` — build `day_queue`, `night_queue` from `DATABASE_URL`.
- [x] T4.2 `queue/tasks.py` — `run_task(ctx, *, task_id, estimated_tokens, endpoint)`.
- [x] T4.3 `queue/hooks.py` — `before_process`, `after_process`; `WindowClosed` exception; reschedule logic.
- [x] T4.4 `queue/worker.py` — SAQ Worker settings + `main()` CLI.

## T5. API
- [x] T5.1 `schemas/tasks.py` — `TaskSubmit`, `TaskResponse`, `QueueType`, `JobStatus`.
- [x] T5.2 `api/deps.py` — FastAPI `Depends()` for repo, queues, settings.
- [x] T5.3 `api/tasks.py` — `POST /tasks`, `GET /tasks/{id}`.
- [x] T5.4 `api/health.py` — `GET /health`.
- [x] T5.5 `main.py` — `create_app()`, include routers, `app.mount("/monitor", saq_web(...))`, startup hook to spawn Monitor.

## T6. Integration tests
- [x] T6.1 `tests/integration/conftest.py` — pg container + alembic upgrade.
- [ ] T6.2 Add an in-repo worker E2E test for a day task.
- [ ] T6.3 Add an in-repo worker E2E test for a scheduled night task.
- [ ] T6.4 Add an in-repo worker E2E test for monitor failure conservative mode.

## T7. Dev ergonomics
- [x] T7.1 `docker-compose.yml` — pinned `postgres:16`.
- [x] T7.2 `Makefile` — `up`, `down`, `migrate`, `dev`, `test`, `worker-day`, `worker-night`, `help`.
- [x] T7.3 `config.toml` — sample endpoints and window.

## Verification gates

After T1–T2: `uv run python -m pytest tests/unit -q` green.
After T3: repository integration test green.
After T4–T5: app boots, smoke POST /tasks works against mock provider.
After T6: full integration suite green.
After T7: `make smoke-up` brings up the dockerized mock stack and `/monitor` renders.
