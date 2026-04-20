# GBrain Minions — Postgres-native Job Queue

Reference notes on Garry Tan's [GBrain](https://github.com/garrytan/gbrain) (MIT, April 2026), specifically its embedded job queue called **Minions**.
Captured here because the design overlaps with headroom's SAQ-backed queue and surfaces ideas we may borrow.

## One-line pitch

A durable, Postgres-native job queue that lives inside the agent runtime so every long-running task survives restarts, streams progress, and can be paused / resumed / steered mid-flight — without Redis, RabbitMQ, or an external scheduler.

## Architecture sketch

```text
                          ┌────────────────────────────────────┐
                          │              gbrain CLI            │
                          │   submit   list   work   stats     │
                          └──────┬────────────────────┬────────┘
                      submit     │                    │   work --concurrency N
                                 v                    v
                        ┌────────────────┐   ┌────────────────────┐
                        │  Job Inserter  │   │    Worker Pool     │
                        │  idem-key dedup│   │  FOR UPDATE SKIP   │
                        │  depth check   │   │        LOCKED      │
                        └────────┬───────┘   └──────────┬─────────┘
                                 │                      │
                                 v                      v
 ┌────────────────────────────────────────────────────────────────────────┐
 │                              Postgres                                  │
 │                                                                        │
 │   jobs ( id, parent_id, status, params, result,                        │
 │          inbox, idem_key, depth, timeout_at, … )                       │
 │                                                                        │
 │   • FOR UPDATE SKIP LOCKED     — fair dispatch                         │
 │   • Recursive CTE              — DAG walk, cascade cancel              │
 │   • LISTEN / NOTIFY            — progress streaming                    │
 │   • PGLite (WASM) in dev       — zero external infra                   │
 │   • Supabase / self-hosted PG  — production                            │
 └────────────┬─────────────────────────────────────────┬─────────────────┘
              ^                                         ^
              │                                         │
      ┌───────┴────────┐                         ┌──────┴─────────┐
      │    Reaper      │                         │     Inbox      │
      │  stall detect  │                         │  steer / cancel│
      │  timeout sweep │                         │   mid-flight   │
      └────────────────┘                         └────────────────┘
```

## Key primitives

- **Single `jobs` table** — durability anchor; rows carry `parent_id` for DAG edges, `inbox` JSON for mid-flight messages, `idem_key` for dedup, `depth` + `timeout_at` for safety caps.
- **`FOR UPDATE SKIP LOCKED`** for worker dispatch; no external broker.
- **Recursive CTEs** for parent→child traversal and cycle prevention; powers cascade cancel and `child_done` fan-in.
- **LISTEN / NOTIFY** to stream progress back to the CLI without polling.
- **Embedded PGLite** (Postgres 17.5 compiled to WebAssembly) for dev; same schema works against Supabase or self-hosted PG in prod.

## Design rule

The README codifies a routing principle:

> **Deterministic** (same input → same steps → same output) → **Minions**
> **Judgment** (input requires assessment) → **Sub-agents**

Deterministic work runs in-process with no LLM round-trip, which is where the published 753 ms / $0.00 numbers come from.

## CLI surface

```text
gbrain jobs submit <name> [--params JSON]
gbrain jobs list   [--status S] [--queue Q]
gbrain jobs work   [--concurrency N]
gbrain jobs stats
gbrain jobs smoke
```

## Published benchmarks

| Metric       | Minions  | Sub-agents            |
| ------------ | -------- | --------------------- |
| Wall time    | 753 ms   | >10 s (timeout)       |
| Token cost   | $0.00    | ~$0.03 per run        |
| Success rate | 100 %    | ~0 % (spawn failures) |

Real workload (19 240 posts, 36 months): Minions ~15 min / $0 vs sub-agents ~9 min best case / $1.08 / ~40 % failure rate.

## Side-by-side with headroom

```text
            ┌────────────┐     ┌────────────┐    ┌─────────────────┐
            │   client   │───▶│  FastAPI   │───▶│ SAQ[postgres]   │
            └────────────┘     │  /tasks    │    │  day / night    │
                               └─────┬──────┘    └────────┬────────┘
                                     │                    │
                                     v                    v
                             ┌────────────────────────────────────┐
                             │             Postgres               │
                             │  jobs(id, queue, status, endpoint, │
                             │       request jsonb, ...)          │
                             │  saq_jobs (SAQ internal)           │
                             └────────────┬─────────────┬─────────┘
                                          ^             ^
                                          │             │
                                   ┌──────┴─────┐ ┌─────┴──────────┐
                                   │  Monitor   │ │  Worker        │
                                   │  Vertex PT │ │  before_process│
                                   │  quota     │ │  capacity +    │
                                   └────────────┘ │  time-window   │
                                                  └────────────────┘
```

| Dimension       | headroom                       | GBrain Minions                 |
| --------------- | ------------------------------ | ------------------------------ |
| Backing store   | Postgres (SAQ library)         | Postgres (custom, PGLite too)  |
| Public surface  | FastAPI + SAQ worker CLI       | `gbrain jobs` CLI only         |
| Job shape       | flat, two queues (day/night)   | arbitrary parent-child DAG     |
| Gating          | capacity gate + night window   | depth / timeout / inbox steer  |
| Streaming       | SAQ dashboard at `/monitor`    | LISTEN/NOTIFY to CLI           |
| Intended load   | LLM calls against Vertex PT    | deterministic agent sub-steps  |
| Dev infra       | docker-compose Postgres 16     | embedded PGLite (no Docker)    |
| Cancellation    | none (MVP non-goal)            | cascade via recursive CTE      |
| Idempotency key | none                           | first-class column             |

## Deep dive: interface and workers

Source read from `garrytan/gbrain@master`: `src/core/minions/{types,queue,worker}.ts`.
Implementation is TypeScript, explicitly "BullMQ-inspired Postgres-native".

### Handler registration

```ts
const queue = new MinionQueue(engine);
const worker = new MinionWorker(engine, { concurrency: 4 });

worker.register('sync', async (ctx) => {
  await runSync(engine, ctx.data);
  return { pages_synced: 42 };
});

await worker.start();           // blocks until SIGTERM/SIGINT
```

A Minion is just a **name → async function** registered on the worker — no decorator, no class hierarchy.
The function signature is `(ctx: MinionJobContext) => Promise<unknown>`, same shape as BullMQ's `Processor`.

### The `MinionJobContext` the handler receives

```ts
interface MinionJobContext {
  id: number;
  name: string;
  data: Record<string, unknown>;
  attempts_made: number;

  signal: AbortSignal;          // fires on timeout, cancel, pause, lock loss
  shutdownSignal: AbortSignal;  // fires only on worker SIGTERM/SIGINT

  updateProgress(progress: unknown): Promise<void>;   // structured, not 0-100
  updateTokens(tokens: TokenUpdate): Promise<void>;   // input/output/cache_read
  log(message: string | TranscriptEntry): Promise<void>;
  isActive(): Promise<boolean>;                       // lock still held?
  readInbox(): Promise<InboxMessage[]>;               // drain unread msgs
}
```

Two separate abort signals is the clever bit.
`signal` is the cooperative cancel token every handler watches.
`shutdownSignal` only fires on deploy restarts, so long handlers don't get killed mid-flight by every SIGTERM — only the handlers that specifically opt in (e.g. the shell handler running a SIGTERM→5s→SIGKILL sequence on its child process) subscribe.

### Submission API

```ts
const job = await queue.add(
  'sync',                                  // handler name
  { full: true },                          // data
  {                                        // opts
    priority: 0,
    max_attempts: 3,
    backoff_type: 'exponential',
    backoff_delay: 1000,
    delay: 5_000,                          // delay_until = now + 5s
    parent_job_id: 17,                     // DAG edge
    on_child_fail: 'fail_parent',          // | 'remove_dep' | 'ignore' | 'continue'
    max_children: 10,
    timeout_ms: 30_000,
    remove_on_complete: true,
    remove_on_fail: false,
    idempotency_key: 'sync:daily:2026-04-20',
    quiet_hours: { start: 22, end: 7, tz: 'America/Los_Angeles', policy: 'defer' },
    stagger_key: 'cron:sync',
  },
);
```

Idempotency is enforced by a partial unique index on `idempotency_key`.
`add()` does a fast-path `SELECT` on the key; on race it falls back to `INSERT … ON CONFLICT DO NOTHING` + a second `SELECT`.
Parent locking is real: `add()` takes `SELECT … FOR UPDATE` on the parent row before the cap check, so two concurrent submits can't both win a `max_children` slot.

### Job status enum

```ts
'waiting' | 'active' | 'completed' | 'failed' | 'delayed'
| 'dead' | 'cancelled' | 'waiting-children' | 'paused'
```

`waiting-children` is the parent's state while its DAG children are still running — not present in most BullMQ clones.

### The claim SQL (literal)

```sql
UPDATE minion_jobs SET
  status = 'active',
  lock_token = $1,
  lock_until = now() + ($2::double precision * interval '1 millisecond'),
  timeout_at = CASE WHEN timeout_ms IS NOT NULL
                    THEN now() + (timeout_ms::double precision * interval '1 millisecond')
                    ELSE NULL END,
  attempts_started = attempts_started + 1,
  started_at = COALESCE(started_at, now()),
  updated_at = now()
 WHERE id = (
   SELECT id FROM minion_jobs
    WHERE queue = $3 AND status = 'waiting' AND name = ANY($4)
    ORDER BY priority ASC, created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
 )
 RETURNING *;
```

Three things to note:

1. **`name = ANY($4)`** — the worker only claims rows whose handler it has registered. Lets you run specialised workers for expensive names on their own box.
2. **`priority ASC, created_at ASC`** — lower `priority` int wins (BullMQ convention), then FIFO.
3. **`FOR UPDATE SKIP LOCKED`** inside a subquery — standard pg queue pattern. The outer `UPDATE` writes lock+timeout in the same statement so claim is a single round-trip.

### Worker loop (pseudo-code)

```text
start():
  ensureSchema()
  on SIGTERM / SIGINT → shutdownAbort.abort()

  every stalledInterval (30s):
    handleStalled()   # lock_until < now → requeue + stalled_counter++
    handleTimeouts()  # timeout_at < now AND lock_until > now → 'dead'

  loop while running:
    promoteDelayed()                    # delay_until < now → 'waiting'
    if inFlight.size < concurrency:
      job = queue.claim(lockToken, lockDuration, queue, registeredNames)
      if job:
        verdict = evaluateQuietHours(job.quiet_hours)
        if verdict == 'defer': status → delayed, delay_until += 15m
        elif verdict == 'skip': cancelJob(job.id)
        else: launchJob(job, lockToken)
      else: sleep(pollInterval | 100ms)
    else: sleep(100ms)

  on stop: wait up to 30s for inFlight to drain
```

### Per-job execution (`launchJob`)

Each claimed job runs as an independent promise in the worker's pool:

- Own `AbortController` — fed to `ctx.signal`.
- Own **lock renewal timer** firing every `lockDuration / 2` (default 15s).
  If `renewLock` returns false (row stolen, status flipped), the controller aborts with `'lock-lost'`.
- Own **wall-clock timeout timer** at `job.timeout_ms`, firing `abort(new Error('timeout'))`.
  The DB-side `handleTimeouts` is the authoritative status flip; the in-process timer is a cooperative signal.
- On settle: `clearInterval(lockTimer)`, `clearTimeout(timeoutTimer)`, `inFlight.delete(job.id)`.

### Complete / fail: all bookkeeping in one txn

`completeJob` and `failJob` do the entire child→parent rollup inside a single transaction to kill the crash-window where a process died between "child done" and "parent resolved".

Steps inside `completeJob(id, lockToken, result)`:

1. Peek `parent_job_id`; if set, `SELECT … FOR UPDATE` the parent (serialises concurrent sibling completions).
2. Token-fenced `UPDATE` of the child: `WHERE id = $id AND status = 'active' AND lock_token = $token`.
3. Roll up `tokens_input / tokens_output / tokens_cache_read` into the parent (guarded against parent terminal).
4. Insert `child_done` message into `minion_inbox` (parent's inbox) with an `EXISTS` guard.
5. Flip parent `waiting-children → waiting` iff `NOT EXISTS` any non-terminal sibling.
6. If `remove_on_complete`, `DELETE` the child row — child_done already lives in the parent's inbox row.

`failJob` runs the mirror logic with the `on_child_fail` policy branch:

- `'fail_parent'` — propagate: mark parent `'failed'` with the child's error.
- `'remove_dep'` — null out child's `parent_job_id`, then try to resolve parent (as if the dep never existed).
- `'ignore' / 'continue'` — no parent action; parent stays in `waiting-children` on remaining siblings.

### Cascade cancel (literal SQL)

```sql
WITH RECURSIVE descendants AS (
  SELECT id, 0 AS d FROM minion_jobs WHERE id = $1
  UNION ALL
  SELECT m.id, descendants.d + 1
    FROM minion_jobs m
    JOIN descendants ON m.parent_job_id = descendants.id
    WHERE descendants.d < 100
)
UPDATE minion_jobs SET
  status = 'cancelled',
  lock_token = NULL,
  lock_until = NULL,
  finished_at = now(),
  updated_at = now()
 WHERE id IN (SELECT id FROM descendants)
   AND status IN ('waiting','active','delayed','waiting-children','paused')
 RETURNING *;
```

The trick: active descendants get `lock_token = NULL`, so on their next lock-renewal tick `renewLock` returns false and the in-process `AbortController` fires.
No cross-process signalling needed — the lock is the signal.

### Inbox and steering

`minion_inbox` is a separate table: `(id, job_id, sender, payload jsonb, sent_at, read_at)`.
Messages are typed (`child_done` is one type; user-defined steering payloads are another).
Handlers drain unread messages with `ctx.readInbox()`, which marks them read in the same query.
There is no LISTEN/NOTIFY on the inbox itself — steering is **poll-driven by the handler**, not pushed.
That's why long-running handlers tend to call `readInbox()` between logical steps.

### How this maps onto headroom

| Concept                | headroom equivalent                               | Notes                                         |
| ---------------------- | ------------------------------------------------- | --------------------------------------------- |
| `worker.register(name, fn)` | SAQ `Worker(functions=[run_task])`           | Minions registers many names per worker       |
| `ctx.signal`           | none — we rely on litellm retries + SAQ retries=0 | worth adding for long gemini calls            |
| `ctx.updateProgress`   | none — we only flip status                        | SAQ has `ctx.progress` but we don't use it    |
| `ctx.readInbox`        | none                                              | would let us cancel a running job             |
| `idempotency_key`      | none                                              | one-line fix: partial unique index on `jobs`  |
| `FOR UPDATE SKIP LOCKED` claim | SAQ's `saq_jobs` internal                 | SAQ already does this; we don't touch it      |
| `waiting-children` state | none                                            | we're flat (day/night), no DAG               |
| cascade cancel         | none                                              | MVP non-goal, but 15 lines of SQL             |
| `quiet_hours` gate     | `is_within_window` in `before_process`            | conceptually identical, ours is hardcoded UTC |

## Ideas worth stealing

- **Idempotency key column** on `jobs` — cheap insurance against double-submit from clients.
- **Recursive-CTE cancel** if we ever add batch cancellation.
- **LISTEN/NOTIFY progress stream** as an alternative to polling `GET /tasks/{id}`.
- **PGLite for local smoke** — could replace the Docker Postgres in `make smoke-*` for contributors who just want `uv run`.

## Sources

- [github.com/garrytan/gbrain](https://github.com/garrytan/gbrain)
- [YC President Garry Tan Open-Sources GBrain — noqta.tn](https://noqta.tn/en/news/garry-tan-gbrain-open-source-ai-agent-memory-2026)
- [GBrain: The Memex We Were Promised — gamgee.ai](https://gamgee.ai/blogs/garry-tan-gbrain-ai-memory-system/)
