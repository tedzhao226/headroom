# Implementation Plan: headroom MVP

**Spec**: [`spec.md`](./spec.md)
**Constitution**: [`/.specify/memory/constitution.md`](../../.specify/memory/constitution.md)
**Created**: 2026-04-17

## Tech stack (from constitution §"Tech stack (locked)")

- Python 3.12+, `uv`
- FastAPI + uvicorn
- SAQ[postgres]
- SQLAlchemy 2.x async + asyncpg
- Alembic
- litellm
- google-cloud-monitoring, google-auth
- pydantic, pydantic-settings, structlog

## Module layout

```
src/headroom/
├── main.py                   # FastAPI app factory, mounts SAQ web UI
├── core/
│   ├── __init__.py
│   ├── config.py             # pydantic-settings + TOML source
│   ├── credentials.py        # GCP SA decoding
│   └── time_window.py        # is_within_window, next_window_start_utc
├── models/
│   ├── __init__.py
│   └── job.py                # SQLAlchemy Job + enums
├── schemas/
│   ├── __init__.py
│   └── tasks.py              # Pydantic request/response
├── repository/
│   ├── __init__.py
│   └── jobs.py               # JobRepository
├── services/
│   ├── __init__.py
│   ├── capacity_gate.py      # CapacityGate Protocol + InMemoryCapacityGate
│   ├── monitor.py            # Monitor Protocol + VertexMonitor + MockMonitor
│   └── provider.py           # Provider Protocol + VertexPTClient + MockProvider
├── queue/
│   ├── __init__.py
│   ├── setup.py              # day_queue, night_queue factory
│   ├── hooks.py              # before_process, after_process
│   ├── tasks.py              # run_task
│   └── worker.py             # CLI entry, wires one queue's worker
└── api/
    ├── __init__.py
    ├── deps.py               # FastAPI Depends()-wired dependencies
    ├── health.py             # GET /health
    └── tasks.py              # POST /tasks, GET /tasks/{id}
migrations/
├── env.py
├── script.py.mako
└── versions/
    └── 0001_create_jobs.py
tests/
├── conftest.py
├── unit/
│   ├── test_capacity_gate.py
│   ├── test_monitor.py
│   ├── test_provider.py
│   ├── test_config.py
│   ├── test_credentials.py
│   └── test_time_window.py
└── integration/
    ├── conftest.py           # testcontainers pg fixture
    ├── test_repository.py
    └── test_end_to_end.py
```

## Data model (`jobs`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `batch_id` | UUID null | future batching |
| `saq_job_id` | text null | SAQ's key for cross-ref |
| `queue` | text CHECK IN (`day`,`night`) | |
| `status` | text CHECK IN (`pending`,`running`,`complete`,`failed`,`cancelled`) | |
| `endpoint` | text | resolved at submit time |
| `request` | jsonb | `{model, messages, parameters}` |
| `result` | jsonb null | `{output, actual_token_count}` |
| `estimated_tokens` | int | |
| `actual_tokens` | int null | set in after_process |
| `reschedule_count` | int default 0 | night-only |
| `created_at` | timestamptz default now() | |
| `started_at` | timestamptz null | |
| `completed_at` | timestamptz null | |
| `error` | text null | |

Index: `(batch_id)`, `(queue, status, created_at)`.

## Sequence — day dispatch

```
client -> POST /tasks -> repo.create(pending) -> day_queue.enqueue(kwargs, retries=0)
                                                           |
saq worker dequeues -> before_process:
    gate.wait_for_capacity(est)    # blocks until can_fit
    gate.reserve(est)
    ctx.tokens_reserved = True
    repo.update_status(running)
                                                           |
run_task:
    provider.call(request) -> LLMResponse
    repo.update_status(complete, result, actual_tokens)
                                                           |
after_process:
    if tokens_reserved:
        gate.release(est)
        gate.report_actual_usage(actual, est)
```

## Sequence — night dispatch

```
client -> POST /tasks (queue=night) -> repo.create(pending)
       -> night_queue.enqueue(kwargs, scheduled=next_window_start_utc(), retries=0)
                                                           |
at 22:00 UTC SAQ dequeues -> before_process:
    if not is_within_window(now_utc):
        if reschedule_count >= 5: raise WindowClosed (permanent failure)
        night_queue.enqueue(kwargs | {reschedule_count+1}, scheduled=next_window_start_utc())
        raise WindowClosed (skip original)
    gate.wait_for_capacity(est); gate.reserve(est); ...
```

## Sequence — monitor refresh

```
monitor.refresh_loop (asyncio.create_task on startup):
    for endpoint in endpoints:
        try:
            usage = await asyncio.to_thread(client.list_time_series, ...)
            gate.update_usage(usage)  # wakes waiters
            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            if >= 5:
                gate.update_usage(min(capacity, max(last_known, int(0.9*capacity))))
    await asyncio.sleep(60)
```

## Config (`config.toml`)

```toml
pt_monitor_interval = 60
pt_monitor_failure_threshold = 5
pt_night_window_start_utc = "22:00"
pt_night_window_end_utc = "06:00"
pt_num_retries = 3
max_reschedules = 5

[[pt_endpoints]]
name = "flash-us"
model = "gemini-2.5-flash"
region = "us-central1"
capacity_tps = 5000

[[pt_endpoints]]
name = "pro-us"
model = "gemini-2.5-pro"
region = "us-central1"
capacity_tps = 3000
```

Env overrides: `DATABASE_URL`, `GCP_PROJECT`, `GCP_SA_KEY`.

## Constitution alignment

- **I. Layered**: `api/` only calls into `services/` and `repository/`; no DB access from routes.
- **II. Protocol**: `CapacityGate`, `Monitor`, `Provider`, `JobRepository` are `typing.Protocol`.
- **III. DI**: queues, repo, gates, monitor are constructed in `main.py`/`worker.py`, injected via `Depends()` / SAQ `ctx`.
- **IV. Async**: every public function `async`, GCP sync client wrapped in `asyncio.to_thread`.
- **V. Postgres-only**: SAQ backend is pg; `jobs` lives on same pg.
- **VI. Gates in `before_process`**: only `run_task` calls the provider.
- **VII. litellm retries**: `num_retries=3` passed to `acompletion`; SAQ `retries=0`.
- **VIII. Fail loudly**: `capacity_gate.report_actual_usage` does not clamp; monitor conservative-mode logs a warning.

## Verification strategy

Aligns with `spec.md` success criteria:

- **SC-001** ↔ `tests/integration/test_end_to_end.py::test_day_task_runs_to_complete` (mock provider)
- **SC-002** ↔ `tests/integration/test_end_to_end.py::test_night_task_scheduled_for_window` (freezegun)
- **SC-003** ↔ `tests/unit/test_capacity_gate.py::test_concurrent_waiters_do_not_oversubscribe`
- **SC-004** ↔ `tests/unit/test_monitor.py::test_conservative_mode_after_n_failures`
- **SC-005** ↔ manual smoke (documented in README + tasks.md)
