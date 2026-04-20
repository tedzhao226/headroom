# headroom

Queue LLM requests against **Vertex AI Provisioned Throughput (PT)** and dispatch
them only when token-per-second capacity allows — with a separate night queue that
also waits for a UTC time window.

Solves a specific problem: PT contracts are billed 24×7 but most daytime usage
fights for the same capacity while nighttime sits idle.
`headroom` absorbs the daytime contention and soaks up the nighttime headroom.

## Why

Vertex AI Provisioned Throughput is capacity you've already paid for.
Without a broker, bursty daytime traffic hits per-second caps and returns 429s while
the overnight hours go unused. Running LLM requests through `headroom` gives you:

- **Graceful back-pressure** — queued not dropped; dispatch when the endpoint has room
- **Night reclaim** — schedule bulk / batch-tolerant jobs into the 22:00–06:00 UTC window
- **Observability** — every 60s, a snapshot of per-endpoint usage is appended to a
  Postgres table so you can answer "was pro-us saturated between 14:00 and 15:00?"
  without Prometheus

## Architecture

```mermaid
flowchart LR
    Client[Client] -->|POST /tasks| API[FastAPI]
    API -->|insert| JOBS[(jobs)]
    API -->|enqueue| SAQ[(saq_jobs)]

    subgraph Postgres
        JOBS
        SAQ
        SAMPLES[(monitor_samples)]
    end

    subgraph Worker[Day / Night Worker]
        BP[before_process<br/>capacity + time gate]
        RUN[run_task]
        BP --> RUN
    end

    SAQ -.->|FOR UPDATE SKIP LOCKED| BP
    RUN -->|call| PROV[Vertex PT<br/>via litellm]
    RUN -->|update| JOBS

    MON[VertexMonitor<br/>poll every 60s] -->|update_usage| GATE[InMemoryCapacityGate]
    MON -->|sample| SAMPLES
    GATE -.->|can_fit?| BP

    GCP[GCP Cloud Monitoring] --> MON
    PROV --> GCP

    DASH[SAQ dashboard<br/>/monitor] --- SAQ
```

Three moving parts:

1. **Monitor** — polls GCP Cloud Monitoring every 60s for per-endpoint
   `token_count` rate, pushes it into each endpoint's capacity gate, and appends one
   row per endpoint to `monitor_samples` for history.
2. **Capacity gate** — in-memory per-endpoint tracker (`usage + reserved ≤ total`).
   Callers block on `asyncio.Condition` until headroom opens up.
3. **Queue** — two SAQ[postgres] queues. `day` = capacity-gated.
   `night` = capacity-gated **and** inside the configured UTC window, otherwise the
   job is rescheduled (up to `max_reschedules`).

Dispatch decisions happen in SAQ's `before_process` hook, not in `run_task` — so the
gate sees the canonical job ID the moment the worker picks it up.

## Night queue semantics

Night jobs are window-gated **at worker pickup**, not throughout their lifetime.
The window check fires once per pickup; the capacity wait that follows is unbounded by the window.

1. **At submit** (`POST /tasks` with `queue: "night"`) the job is enqueued with
   `scheduled = next_window_start_utc(...)`.
   SAQ holds it in `saq_jobs` until the next window opens (default 22:00 UTC) — the
   worker doesn't poll or wake on it before then.
2. **At pickup** (`before_process`) the worker re-checks the window.
   If the job somehow lands outside it (manual enqueue without `scheduled`, config
   change mid-flight, clock skew) it's re-enqueued once with `scheduled` set to the
   next window start.
   This repeats up to `max_reschedules`, after which the job is marked `FAILED` with
   `"max reschedules reached"`.
   Each reschedule defers to a strictly-future timestamp, so there is no busy loop.
3. **During the capacity wait** the window is **not** re-checked.
   Once `is_within_window(...)` passes, the job blocks on
   `gate.wait_for_capacity(estimated_tokens)`.
   If the endpoint stays saturated past 06:00 UTC, the job will still dispatch the
   moment headroom opens — even into the daytime.

This is intentional.
A job that has already been picked up holds a slot in `night_queue_concurrency` and
has a row updated to `RUNNING` only after capacity is reserved; cancelling it
mid-wait to re-enqueue would thrash the queue and lose FIFO ordering against other
waiting night jobs.
The trade is: night-queue jobs are *best-effort overnight*, not *guaranteed
overnight*.
If you need a hard cutoff (no dispatch outside the window, ever), add a deadline
to the capacity wait or re-check the window immediately before `gate.reserve(...)`
in `src/headroom/queue/hooks.py`.

## Stack

- **FastAPI** — thin HTTP API (Router → Service → Repository)
- **SAQ[postgres]** — task queue backed by Postgres (no Redis)
- **Postgres 16** — queue tables + `jobs` + `monitor_samples`
- **SQLAlchemy 2 + asyncpg** — async ORM
- **Alembic** — migrations
- **litellm** — LLM client with retry (`num_retries`; SAQ `retries=0`)
- **google-cloud-monitoring** — Vertex PT token metrics
- **pydantic-settings** — config via TOML + env
- **testcontainers[postgres]** — integration tests against a real Postgres

## Quickstart — dockerized mock stack

No GCP credentials needed. Uses `MockProvider` + `MockMonitor`.

```bash
make smoke-up     # build + start db, api, both workers
make smoke-run    # submit 5 day tasks, poll until complete
make smoke-down   # tear it all down
```

- API: `http://localhost:8000` · health: `/health` · dashboard: `/monitor/`
- Postgres: `postgresql://headroom:headroom@localhost:5432/headroom`
  (same URL works in DataGrip / psql)

## Quickstart — local dev (real GCP)

```bash
uv sync
cp .env.example .env            # fill in GCP_PROJECT and GCP_SA_KEY
make up && make migrate         # postgres + schema
make dev                        # uvicorn with reload
make worker-day                 # in another shell
make worker-night               # in another shell
```

Submit a task:

```bash
curl -XPOST http://localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{
    "queue": "day",
    "model": "gemini-2.5-flash",
    "messages": [{"role": "user", "content": "hi"}],
    "estimated_tokens": 500
  }'
```

## Configuration

`config.toml` — pinned, non-secret:

```toml
pt_monitor_interval = 60
pt_monitor_failure_threshold = 5
pt_night_window_start_utc = "22:00"
pt_night_window_end_utc   = "06:00"
day_queue_concurrency     = 10
night_queue_concurrency   = 3

[[pt_endpoints]]
name = "flash-us"
model = "gemini-2.5-flash"
region = "us-central1"
capacity_tps = 5000
```

`.env` — secrets only (`DATABASE_URL`, `GCP_PROJECT`, `GCP_SA_KEY`). See `.env.example`.

## Observability

- **`/health`** — snapshot of every gate: `total_tps`, `current_usage_tps`,
  `reserved_tokens`, `available`.
- **`/monitor/`** — SAQ dashboard for queue depth / workers / recent jobs.
- **`monitor_samples`** — append-only Postgres table, one row per endpoint per
  monitor tick. Example query:

  ```sql
  SELECT endpoint, recorded_at, usage_tps, reserved_tokens, available, status
  FROM monitor_samples
  WHERE endpoint = 'flash-us'
    AND recorded_at > now() - interval '1 hour'
  ORDER BY recorded_at DESC;
  ```

  `status` is `'ok'` while the monitor is getting clean reads from GCP, and
  `'stale'` once `consecutive_failures ≥ pt_monitor_failure_threshold` — at which
  point the gate switches to a conservative estimate so we don't over-dispatch
  blindly.

## Tests

```bash
make test                                # full suite
uv run pytest tests/unit -q              # fast unit tests
uv run pytest tests/integration -q       # spins up testcontainers Postgres
```

Currently 68 tests (60 unit + 8 integration).

## Layout

```
src/headroom/
├── main.py                   # FastAPI app factory; SAQ dashboard mount
├── core/                     # config, credentials, time windows
├── models/                   # SQLAlchemy ORM
├── repository/               # jobs + monitor_samples repos
├── services/                 # capacity_gate, monitor, provider
├── queue/                    # SAQ setup, hooks, tasks, worker entrypoint
└── api/                      # health, tasks routes
migrations/versions/          # alembic: 0001_create_jobs, 0002_monitor_samples
scripts/smoke.py              # stdlib-only end-to-end client
tests/unit · tests/integration
specs/001-headroom-mvp/       # spec-kit spec, plan, tasks
.specify/memory/constitution.md
```

## Non-goals

Explicit (from `.specify/memory/constitution.md`):

- No Redis anywhere
- No Prometheus export — `monitor_samples` + direct SQL covers observability
- No multi-process / distributed capacity gate — single in-memory gate per worker
- No batch submit, no cancellation API, no custom auth (deployment concern)
