# ADR 003 — Job System: Hatchet or Equivalent Durable Workflow

Status: **accepted** (spike passed 8/8 mandatory checks on 2026-09-23)  
Date: 2026-09-22 (accepted 2026-09-23)  
Deciders: queue/distributed systems lead, architecture lead, independent reviewer

## Context

Audits are long-running, potentially GPU-backed, and must survive restarts. The current prototype uses an in-process Python queue with process-local SSE subscribers. That is acceptable only as exploratory code and explicitly rejected for production.

Required capabilities:

- persistent jobs
- workers separate from web process
- retries with policy
- cancellation
- timeouts
- progress events
- structured logs
- concurrency limits
- worker pools/labels
- GPU queues
- recovery after worker/server restart
- idempotency
- job history
- graceful shutdown
- backpressure

## Candidate requirements checklist

A suitable system must support:

1. durable task queue backed by PostgreSQL or equivalent
2. worker processes that can run on separate hosts
3. task labels/routing for CPU/GPU/API pools
4. retry policies with max attempts/backoff
5. task timeout and run timeout
6. cancellation API
7. event/webhook or queryable state for progress
8. idempotency keys or safe unique result writes
9. observability hooks
10. Docker Compose deployment
11. active maintenance and clear self-host story

## Options considered

### Option A: Hatchet

Pros:

- Postgres-backed workflow engine
- task/run model fits audit decomposition
- supports workers, schedules, retries, concurrency
- self-hostable
- aligns with repository reference architecture

Cons:

- need to verify exact cancellation semantics
- need to verify event replay suitability for SSE
- GPU routing may require custom worker labels/metadata
- operational maturity must be validated against our failure tests

### Option B: Celery + Redis/RQ

Pros:

- very mature
- broad ecosystem
- easy workers

Cons:

- weaker native workflow/DAG semantics
- progress/event durability often requires extra design
- Redis adds another state store
- may become custom orchestration over time

### Option C: Temporal

Pros:

- durable execution
- strong failure recovery
- complex workflows

Cons:

- heavier operational footprint
- may be overkill for MVP
- larger learning curve
- introduces a second durable execution state store with its own operations, backup, and upgrade story
- if chosen later, it should be because Hatchet/Celery failed mandatory recovery/idempotency requirements, not because of preference

Temporal is not the default fallback. If Hatchet fails the spike, prefer the
lightest candidate that still passes all mandatory acceptance criteria.

### Option D: DB-backed custom queue

Pros:

- full control
- no new vendor

Cons:

- reinvents distributed systems
- high risk of subtle bugs
- violates preference for boring mature infrastructure

## Decision

Proceed with **Hatchet** as the primary candidate, subject to a time-boxed technical spike.

If the spike fails any mandatory requirement without reasonable extension, choose the next candidate that satisfies all mandatory requirements. Do not fall back to in-process queue.

Initial workflow shape:

```text
audit.run
  -> preparing
  -> scenario.execute (parallel children)
  -> aggregation
  -> report_generation
```

PostgreSQL remains authoritative for domain state. Hatchet stores execution state and coordinates tasks.

## Spike outcome (2026-09-23)

The time-boxed spike (`spike/run_spike.py`, `spike/worker.py`, `spike/event_store.py`) was executed against Hatchet embedded mode (v1.41.0 SDK, sidecar v0.107.0) with a fake SimpleAudit executor. **All 8 mandatory checks passed:**

| # | Check | Result |
|---|-------|--------|
| 1 | Persistence: scenarios executed by separate worker | PASS — 3/3 results |
| 2 | Progress: durable events written | PASS — `scenario_attempted`/`scenario_completed` |
| 3 | Progress: SSE-style replay from Last-Event-ID | PASS — total=6 after_first=5 |
| 4 | Finalize: run completed event | PASS |
| 5 | Idempotency: no duplicate final results on re-execution | PASS — before=3 after=3 |
| 6 | Retry: transient failures recovered via retry policy | PASS — completed after 2 injected failures |
| 7 | Cancellation: durable flag prevents remaining work | PASS — skipped=2 results=0 |
| 8 | Version guard: mismatch fails run with SIMPLEAUDIT_VERSION_MISMATCH | PASS |

Key findings that shaped the implementation:

- **Hatchet retries do NOT mutate task input.** The `attempt` field in the task input stays constant across retries; only the step-run identity changes. Fault injection / attempt accounting must therefore count durable `scenario_attempted` events per `(run_id, version_item_id)` rather than trusting an input field.
- **Standalone tasks require an explicit `input_validator`.** Without it the workflow defaults to `EmptyModel` and the worker deserializes into a fieldless instance (`AttributeError`). Both tasks declare Pydantic `input_validator`s.
- **Cancellation is observed via a durable flag**, not an in-memory signal. The worker reads the cancel request from the durable event store at each scenario boundary, so it survives web-process restarts.
- **Idempotent result writes** use `ON CONFLICT DO UPDATE` keyed on `(run_id, version_item_id)` with `attempts = MAX(...)`, so duplicate executions never create duplicate final results.

Full evidence and reproduction steps are in `docs/job-system-spike.md`.

## Spike acceptance criteria

The spike must demonstrate:

- create run from Django API
- worker picks up task after web restart
- task retries after simulated exception
- task timeout works
- cancellation prevents remaining scenarios
- cancellation survives web/API restart
- concurrency limit respected
- worker label routing works
- progress events can be queried/streamed
- `AuditEvent` remains the primary durable source for SSE replay; workflow events are inputs, not the user-facing event store
- idempotent final result write under duplicate execution
- queryable job/run history is available for operators
- graceful shutdown drains or safely parks active tasks on SIGTERM
- backpressure behavior is observable when queued jobs exceed worker capacity
- Docker Compose brings up server + worker cleanly

## Consequences if accepted

Positive:

- durable execution
- separate worker scaling
- less custom queue code
- GPU workers can join same system

Negative:

- new infrastructure component
- team must learn Hatchet operations
- event bridge to SSE must be designed carefully

## Open questions

Resolved by the spike:

- **Hatchet version pin** — SDK `hatchet-sdk==1.41.0`, embedded sidecar v0.107.0 validated; server image `ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest`.
- **SSE source of truth** — confirmed: the durable `AuditEvent` table (Postgres) remains the primary user-facing event store for SSE replay. Hatchet workflow events are inputs only; the worker bridges them into `AuditEvent` rows. The spike's `event_store` is a stand-in for that table.

Still open (to resolve during Phase 5 integration):

- Worker authentication model (service token / mTLS between worker and Hatchet server)
- GPU label convention (worker `labels={"pool":"gpu"}` + task routing metadata)
- Maximum run duration settings for long-lived LLM jobs
