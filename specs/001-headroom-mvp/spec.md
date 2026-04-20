# Feature Specification: headroom MVP

**Feature Branch**: `001-headroom-mvp`
**Created**: 2026-04-17
**Status**: Draft
**Input**: "A minimal system that monitors Vertex AI PT capacity, gates LLM calls on capacity + time window, and queues jobs via SAQ[postgres]."

## User Scenarios & Testing

### User Story 1 — Submit a day-time task (Priority: P1)

A client submits an LLM job to the `day` queue. The job persists immediately, and a worker dispatches it as soon as PT capacity is available.

**Why this priority**: This is the simplest, highest-value path — the one all other flows build on.

**Independent Test**: `POST /tasks` with `queue="day"` returns a task id; the job row is `pending`; a worker picks it up, calls the provider, and the row flips to `complete` with an `actual_token_count`.

**Acceptance Scenarios**:
1. **Given** PT has free capacity, **When** a day task is submitted, **Then** it dispatches within seconds and the response becomes `complete`.
2. **Given** PT is at capacity, **When** a day task is submitted, **Then** it sits in the queue until Monitor reports headroom and then dispatches.
3. **Given** a fatal provider error (e.g. 400), **When** the worker calls litellm, **Then** the task transitions to `failed` with `error` set, and reserved tokens are released.

---

### User Story 2 — Submit a night-only task (Priority: P2)

A client submits a backlog job to the `night` queue. The job is held until the UTC night window (default 22:00–06:00) and then dispatches when capacity is available.

**Why this priority**: Shifts non-urgent batch work to off-peak PT capacity.

**Independent Test**: `POST /tasks` with `queue="night"` at 12:00 UTC returns a task id with `scheduled=next 22:00 UTC`; the worker does not dispatch before 22:00. Inside the window, it dispatches when capacity allows.

**Acceptance Scenarios**:
1. **Given** the current time is outside the window, **When** a night task is submitted, **Then** it persists as `pending` and is not dispatched until the window opens.
2. **Given** a night task starts during the window but the window closes before dispatch, **When** `before_process` runs outside the window, **Then** a replacement task is enqueued for the next window (up to 5 reschedules), and the original is marked failed.
3. **Given** 5 consecutive missed windows, **When** the sixth dispatch fails the window check, **Then** the task is marked `failed` permanently with `error="max reschedules reached"`.

---

### User Story 3 — Observe system state (Priority: P2)

An operator opens `/monitor` and inspects queue depth, running jobs, and failures using SAQ's built-in dashboard.

**Why this priority**: Without visibility, operating the service is guesswork. SAQ provides this out of the box, so the cost is low.

**Independent Test**: Navigate to `/monitor` in a browser with both queues defined. See pending/active/failed counts update as jobs progress.

**Acceptance Scenarios**:
1. **Given** jobs are queued, **When** the operator visits `/monitor`, **Then** the SAQ dashboard shows both queues and their job counts.
2. **Given** a job failed, **When** the operator drills into the job, **Then** they can see kwargs, error, and timing.

---

### Edge Cases

- **Monitor outage**: if the GCP Monitoring API is unreachable, the gate keeps the last-known usage; after N consecutive failures (default 5) it switches to conservative mode (assumes ≥90% of capacity is consumed).
- **Clock skew / DST**: all time comparisons are in UTC; `pt_night_window_start_utc` and `pt_night_window_end_utc` are stored as `datetime.time` and interpreted in UTC.
- **Over-release of tokens**: if `after_process` is called twice for the same job, the gate does NOT clamp reserved tokens to zero — the accounting stays visibly wrong so tests catch it.
- **Worker restart mid-job**: after restart, `_reserved_tokens` and `_current_usage_tps` reset to 0. Monitor repopulates within 60 s. SAQ re-queues the interrupted job via its own recovery.
- **Large estimated tokens**: if `estimated_tokens` exceeds `capacity_tps`, the gate will block forever. Spec requires rejecting such submissions with HTTP 400 at the API layer.

## Requirements

### Functional Requirements

- **FR-001**: `POST /tasks` MUST persist a `jobs` row with status `pending` before returning.
- **FR-002**: `POST /tasks` MUST enqueue the job into the SAQ queue identified by `queue` (`day` or `night`).
- **FR-003**: `POST /tasks` MUST reject with HTTP 400 if `estimated_tokens > endpoint.capacity_tps` for the selected endpoint.
- **FR-004**: `POST /tasks` MUST select the endpoint by matching `model` to the `pt_endpoints` config; if multiple endpoints match, an `endpoint` field MUST be provided.
- **FR-005**: For `night` jobs, the API MUST compute `scheduled = next_night_window_start_utc()` and pass it to SAQ.
- **FR-006**: The SAQ `before_process` hook MUST block (via `capacity_gate.wait_for_capacity`) until capacity is available, then reserve the estimated tokens.
- **FR-007**: The SAQ `before_process` hook MUST check the UTC window for `night` jobs; if outside the window, it MUST re-enqueue with `scheduled=next_night_window_start_utc()` and raise to skip, unless `reschedule_count >= 5` in which case the job fails permanently.
- **FR-008**: The SAQ `after_process` hook MUST release reserved tokens for any job that reached `reserve()`, and MUST reconcile actual usage for successful jobs.
- **FR-009**: The Monitor MUST poll GCP every 60 s and call `gate.update_usage(tps)` for each configured endpoint.
- **FR-010**: After 5 consecutive Monitor failures for an endpoint, the gate MUST be set to a conservative usage value (max of last-known usage and 90% of capacity).
- **FR-011**: `GET /tasks/{id}` MUST return the current status and fields of the job.
- **FR-012**: `GET /health` MUST return 200 with a JSON body summarizing per-endpoint capacity and monitor state.
- **FR-013**: The SAQ web dashboard MUST be mounted at `/monitor`.

### Key Entities

- **Job** — a persisted task row. Fields: `id` (UUID), `queue`, `status` (`pending|running|complete|failed|cancelled`), `request` (JSONB: model, messages, parameters), `result` (JSONB), `estimated_tokens`, `actual_tokens`, timestamps (`created_at`, `started_at`, `completed_at`), `error`, `saq_job_id`, `batch_id` (nullable, reserved for future batching).
- **Endpoint** — PT deployment. Config: `name`, `model`, `region`, `capacity_tps`. Each endpoint has its own `CapacityGate` instance.
- **CapacityGate** — in-memory, per-endpoint. Tracks `total_capacity`, `current_usage_tps` (from Monitor), and `reserved_tokens` (from in-flight jobs).
- **Monitor** — background task that polls GCP Cloud Monitoring every 60 s and updates each endpoint's gate.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A day task submitted when capacity is free transitions `pending → running → complete` within 10 seconds (mock provider in tests).
- **SC-002**: A night task submitted at 12:00 UTC is held until ≥22:00 UTC before dispatching.
- **SC-003**: When 20 concurrent waiters request 500 tokens on a 5,000-token endpoint that starts with 0 headroom and Monitor then reports 4,500 tps usage, no more than 1 waiter proceeds per 500-token slot; total reservations never exceed 5,000.
- **SC-004**: With GCP Monitoring disabled for 5 minutes, the gate switches to conservative mode; no task dispatches beyond 10% of configured capacity during that window.
- **SC-005**: `/monitor` renders and lists both queues when a smoke submission is running.

## Assumptions

- Single-process deployment. Multi-process / distributed capacity gating is out of scope.
- No authentication on `/tasks` or `/monitor` — deployment layer (reverse proxy / auth middleware) handles that.
- All submissions provide `estimated_tokens`. Token estimation is the caller's responsibility.
- Postgres is reachable at `DATABASE_URL`; service crashes loudly if not.
- GCP service account credentials are provided via `GCP_SA_KEY` (base64-encoded JSON).

## Non-goals

- Batch submission (`POST /tasks/batch`) and `DELETE /tasks/{id}` cancellation — deferred to later specs.
- Prometheus metrics export — defer.
- On-demand fallback when PT is saturated — defer.
