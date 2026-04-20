# Tasks: headroom MVP

**Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

Tasks are grouped by module. Each is independently runnable and verifiable. Work top-to-bottom — earlier tasks unblock later ones.

## T1. Core config and credentials
- [ ] T1.1 `src/headroom/core/config.py` — `EndpointConfig`, `Settings` with TOML source.
- [ ] T1.2 `src/headroom/core/credentials.py` — `get_gcp_credentials()` from `GCP_SA_KEY`.
- [ ] T1.3 `src/headroom/core/time_window.py` — `is_within_window(now, start, end)`, `next_window_start_utc(start)`.
- [ ] T1.4 Tests: `tests/unit/test_config.py`, `test_credentials.py`, `test_time_window.py`.

## T2. Services (port from pt_headroom)
- [ ] T2.1 `services/capacity_gate.py` — `CapacityGate` Protocol, `InMemoryCapacityGate`.
- [ ] T2.2 `services/monitor.py` — `Monitor` Protocol, `VertexMonitor`, `MockMonitor`.
- [ ] T2.3 `services/provider.py` — `Provider` Protocol, `VertexPTClient`, `MockProvider`.
- [ ] T2.4 Tests: `tests/unit/test_capacity_gate.py`, `test_monitor.py`, `test_provider.py`.

## T3. Persistence
- [ ] T3.1 `models/job.py` — SQLAlchemy `Job` + `QueueType`, `JobStatus` enums.
- [ ] T3.2 `alembic.ini` + `migrations/env.py` + `migrations/versions/0001_create_jobs.py`.
- [ ] T3.3 `repository/jobs.py` — `JobRepository` Protocol + SQLAlchemy impl.
- [ ] T3.4 Integration test: `tests/integration/test_repository.py` (testcontainers pg).

## T4. Queue
- [ ] T4.1 `queue/setup.py` — build `day_queue`, `night_queue` from `DATABASE_URL`.
- [ ] T4.2 `queue/tasks.py` — `run_task(ctx, *, task_id, estimated_tokens, endpoint)`.
- [ ] T4.3 `queue/hooks.py` — `before_process`, `after_process`; `WindowClosed` exception; reschedule logic.
- [ ] T4.4 `queue/worker.py` — SAQ Worker settings + `main()` CLI.

## T5. API
- [ ] T5.1 `schemas/tasks.py` — `TaskSubmit`, `TaskResponse`, `QueueType`, `JobStatus`.
- [ ] T5.2 `api/deps.py` — FastAPI `Depends()` for repo, queues, settings.
- [ ] T5.3 `api/tasks.py` — `POST /tasks`, `GET /tasks/{id}`.
- [ ] T5.4 `api/health.py` — `GET /health`.
- [ ] T5.5 `main.py` — `create_app()`, include routers, `app.mount("/monitor", saq_web(...))`, startup hook to spawn Monitor.

## T6. Integration tests
- [ ] T6.1 `tests/integration/conftest.py` — pg container + alembic upgrade + app factory fixture.
- [ ] T6.2 `test_end_to_end.py::test_day_task_runs_to_complete` (mock provider, in-proc SAQ worker).
- [ ] T6.3 `test_end_to_end.py::test_night_task_scheduled_for_window` (freezegun).
- [ ] T6.4 `test_end_to_end.py::test_monitor_failure_triggers_conservative_mode`.

## T7. Dev ergonomics
- [ ] T7.1 `docker-compose.yml` — pinned `postgres:16`.
- [ ] T7.2 `Makefile` — `up`, `down`, `migrate`, `dev`, `test`, `worker-day`, `worker-night`, `help`.
- [ ] T7.3 `config.toml` — sample endpoints and window.

## Verification gates

After T1–T2: `uv run pytest tests/unit -q` green.
After T3: repository integration test green.
After T4–T5: app boots, smoke POST /tasks works against mock provider.
After T6: full integration suite green.
After T7: `make dev` brings up the whole stack locally and `/monitor` renders.
