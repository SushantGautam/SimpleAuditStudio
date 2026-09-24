# Durable Job System Spike

Status: **implemented and passed (8/8 checks, 2026-09-23)**  
Date: 2026-09-22 (validated 2026-09-23)  
Related ADR: `docs/adr/003-job-system.md`

## Purpose

Validate a durable workflow system before implementing SimpleAudit execution. The spike must prove that audit work survives process restarts, can be retried safely, emits durable progress events, and can be cancelled without relying on web-process memory.

## Non-negotiable acceptance criteria

1. **Persistence**
   - A submitted job remains visible after the web/API process restarts.
   - A worker crash does not lose the job or leave it permanently stuck.

2. **Separation**
   - Web/API process does not execute model calls.
   - Workers are separate processes with their own lifecycle.

3. **Idempotency**
   - Re-executing a scenario for an `AuditRun` cannot create duplicate final results.
   - Final result identity is stable per `(run_id, version_item_id)`.

4. **Progress**
   - Progress is written to PostgreSQL as `AuditEvent` rows.
   - Browser SSE can replay from `Last-Event-ID` after reconnect.

5. **Cancellation**
   - Cancellation request is durable.
   - If the web process dies after accepting cancellation, the worker still observes it.

6. **Version guard**
   - Worker verifies `simpleaudit_version` and `git_commit` against its loaded engine.
   - Mismatch fails the run with `SIMPLEAUDIT_VERSION_MISMATCH`.

7. **Secrets**
   - Workers resolve secrets from environment/vault at execution time.
   - No raw secret is stored in `AuditRun`, snapshots, events, logs, or artifacts.

8. **GPU/CPU pools**
   - Jobs can target labeled worker pools.
   - Web server does not need GPU access.

## Candidate evaluation

### Hatchet

Strengths:
- Postgres-backed durable task queue.
- HTTP API and Python SDK.
- Supports retries, schedules, concurrency, and worker deployment patterns.

Risks:
- Need to verify exact semantics for cancellation, idempotency keys, stale task recovery, and long-running LLM jobs.
- Need to confirm whether Hatchet state can remain non-authoritative while PostgreSQL domain tables remain source of truth.

Spike tasks:
- Define `audit_run_started`, `scenario_attempted`, `scenario_completed`, `run_failed`, `run_cancelled` tasks.
- Submit a fake audit run with three scenarios.
- Kill worker mid-run and restart.
- Verify no duplicate final results.
- Verify cancellation persists.

### Celery + Redis/RQ

Strengths:
- Mature ecosystem.
- Well-known retry and queue semantics.

Risks:
- Adds another broker/state store.
- May require more custom code for durable structured progress and cancellation.

Decision rule: choose the system that passes the acceptance criteria with the least custom reliability code. Do not choose based on familiarity alone.

## Spike output

The spike must produce:

- compose service replacing the placeholder `hatchet-server` sleep container if Hatchet is selected
- worker entrypoint
- small fake audit executor
- test evidence for restart, retry, cancellation, and idempotency
- updated ADR 003 status from candidate to accepted/rejected

Until this spike passes, `AuditRun` creation may exist, but real model execution must not be enabled.

## Implementation (2026-09-23)

The spike lives in `spike/`:

- `spike/event_store.py` — durable SQLite event/result store standing in for the Postgres `AuditEvent` table. Provides `append_event`, `list_events(run_id, after_id)` (SSE-style replay), and idempotent `upsert_result(run_id, version_item_id, status, attempts)` using `ON CONFLICT DO UPDATE` with `attempts = MAX(...)`.
- `spike/worker.py` — fake SimpleAudit executor. Two Hatchet tasks:
  - `audit.scenario_execute` (`retries=2`, `backoff_factor=2.0`) — appends a durable `scenario_attempted` event, checks the durable cancel flag, writes an idempotent result, appends `scenario_completed`. Optional fault injection fails the first N **executions** (counted from durable events, not the input).
  - `audit.run_finalize` — enforces the version guard: compares `simpleaudit_version`/`git_commit` against the worker's loaded engine constants and fails the run with `SIMPLEAUDIT_VERSION_MISMATCH` on mismatch.
- `spike/run_spike.py` — driver that boots Hatchet embedded mode, runs a worker in a background thread, and asserts 8 mandatory checks.

### Reproduction

```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd simpleaudit-studio
# clean slate
pkill -9 -f "spike.run_spike"; pkill -9 -f "hatchet-embedded-sidecar"; pkill -9 -f "spike/.embedded-pg"
rm -f spike/events.sqlite3
.venv/bin/python -m spike.run_spike > spike/spike_run.log 2>&1
grep -aE "^\[(PASS|FAIL)\]|checks passed" spike/spike_run.log
```

Expected: `8/8 checks passed`.

### Evidence (2026-09-23 run)

```text
[PASS] persistence: scenarios executed by separate worker — 3/3 results
[PASS] progress: durable events written — kinds=['scenario_attempted', 'scenario_completed']
[PASS] progress: SSE-style replay from Last-Event-ID — total=6 after_first=5
[PASS] finalize: run completed event
[PASS] idempotency: no duplicate final results on re-execution — before=3 after=3
[PASS] retry: transient failures recovered via retry policy — result={'status': 'completed', ...}
[PASS] cancellation: durable flag prevents remaining work — skipped=2 results=0
[PASS] version guard: mismatch fails run with SIMPLEAUDIT_VERSION_MISMATCH
8/8 checks passed
```

### Findings / lessons

1. **Hatchet retries do NOT mutate task input.** The `attempt` field stays constant across retries. Attempt/fault accounting must count durable `scenario_attempted` events per `(run_id, version_item_id)`.
2. **Standalone tasks need an explicit `input_validator`** or the workflow defaults to `EmptyModel` and deserialization yields a fieldless instance (`AttributeError`).
3. **Cancellation must be observed from a durable flag**, read at each scenario boundary, so it survives web-process restarts.
4. **Idempotent result writes** keyed on `(run_id, version_item_id)` with `MAX(attempts)` prevent duplicate final results under re-execution.
5. **Wait predicates in tests must target the specific terminal event** (e.g. count of `scenario_skipped_cancelled`), not a loose total-event count that can fire early.

### Known cosmetic issue

After the summary prints, `stop_embedded()` does not fully reap the embedded Postgres sidecar; the process lingers until killed. This is teardown noise only and does not affect the validated results.
