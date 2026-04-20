# headroom Constitution

These are the non-negotiable principles for the `headroom` project.
Every spec, plan, task, and implementation must comply.
Exceptions require amending this document first.

## Core Principles

### I. Layered architecture
Router → Service → Repository.
API handlers stay thin: parse request, call a service, return a response.
Business logic lives in services.
Data access lives in repositories and returns domain models (not ORM rows) to callers.

### II. Protocol over ABC
Define interfaces with `typing.Protocol`, never `abc.ABC`.
Implementations are plain classes or dataclasses that structurally match the protocol.
Makes substitution (mock ↔ real) trivial; no inheritance trees.

### III. Dependency injection
Pass dependencies as constructor arguments or via FastAPI `Depends()`.
No module-level singletons for mutable state.
No globals for the database session, the queue, the capacity gate, or credentials.

### IV. Async-only
All I/O is `async` — FastAPI routes, SAQ jobs, SQLAlchemy (asyncpg), litellm (`acompletion`).
Single event loop per process.
Blocking calls (e.g. google-cloud-monitoring's sync client) are wrapped in `asyncio.to_thread()`.

### V. Postgres-only backend (NON-NEGOTIABLE)
The queue uses `saq[postgres]`. Job state and results persist in a `jobs` table on the same Postgres.
No Redis. No in-memory queue. No external job store.

### VI. Gates in `before_process`, not `run_task`
The capacity gate and time-window gate run in SAQ's `before_process` hook.
`run_task` only calls the provider and stores the result.
`after_process` always releases reserved tokens (success or failure).

### VII. litellm owns retries
Transient LLM failures (429, 503, timeout) are retried inline by litellm via `num_retries`.
SAQ jobs run with `retries=0`.
Capacity reservation holds for the full call including retries; released once in `after_process`.

### VIII. Fail loudly on invariants
If the capacity gate's accounting temporarily goes negative, surface it — don't clamp.
If the monitor fails repeatedly, switch to a conservative fallback and log warnings; don't zero capacity silently.

## Tech stack (locked)

- Python 3.12+, managed by `uv`
- FastAPI + uvicorn
- SAQ[postgres]
- SQLAlchemy 2.x (async) + asyncpg
- Alembic
- litellm
- google-cloud-monitoring, google-auth
- pydantic 2.x, pydantic-settings
- structlog

Swapping any of these requires a constitution amendment.

## Quality gates

- Every public function has type hints.
- Every service has unit tests (mock collaborators).
- Every cross-layer flow (API → queue → worker → repo) has an integration test using a real Postgres via `testcontainers`.
- `uv run pytest -q` is green before anything is called "done".

## Governance

This constitution supersedes all other guidance.
Amendments: edit this file first, note the change, then update dependent specs/plans/tasks.

**Version**: 1.0.0 | **Ratified**: 2026-04-17 | **Last Amended**: 2026-04-17
