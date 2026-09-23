"""Spike worker: a fake SimpleAudit executor driven by Hatchet (embedded mode).

This proves the durable-job acceptance criteria WITHOUT any real model calls:

- ``scenario.execute`` is a standalone task per scenario, so each scenario has a
  stable identity of ``(run_id, version_item_id)``.
- Final results are written idempotently to the event store keyed on that pair,
  so duplicate execution cannot create duplicate final results.
- Progress is appended as durable events (stand-in for Postgres AuditEvent rows).
- A cancellation flag in the durable store is checked between scenarios, so a
  cancel survives a web-process restart (the worker reads it from the store, not
  from memory).
- The engine provenance guard fails the run on version mismatch.

Run directly to start an embedded engine + worker:
    python -m spike.worker
"""
from __future__ import annotations

import os
import time

from pydantic import BaseModel

from hatchet_sdk import ClientConfig, Context, EmbeddedHatchetConfig, Hatchet, Worker

from . import event_store


class ScenarioInput(BaseModel):
    run_id: str
    version_item_id: str
    attempt: int = 1


class FinalizeInput(BaseModel):
    run_id: str
    simpleaudit_version: str | None = None
    git_commit: str | None = None

# Engine provenance the worker "loaded". In production this is read from the
# installed SimpleAudit package + git describe at worker startup.
WORKER_SIMPLEAUDIT_VERSION = os.environ.get("SPIKE_ENGINE_VERSION", "0.1.0")
WORKER_GIT_COMMIT = os.environ.get("SPIKE_ENGINE_GIT_COMMIT", "deadbeef")

_CLIENT: "Hatchet | None" = None


def get_client() -> Hatchet:
    """Return the single shared embedded Hatchet client for this process.

    Both the worker and the submission driver must use this same instance so
    tasks are submitted to the engine the worker actually listens on.
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Hatchet.from_embedded(
            ClientConfig(
                embedded=EmbeddedHatchetConfig(
                    # Isolate the embedded Postgres data dir per spike run.
                    postgres_data_dir=os.environ.get("SPIKE_EMBEDDED_PG_DIR", "spike/.embedded-pg"),
                    log_level="warn",
                )
            )
        )
    return _CLIENT


def _is_cancelled(run_id: str) -> bool:
    """Cancellation is durable: read from the event store, never process memory."""
    return any(e["kind"] == "run_cancel_requested" for e in event_store.list_events(run_id))


@get_client().task(
    name="audit.scenario_execute",
    input_validator=ScenarioInput,
    retries=2,
    backoff_factor=2.0,
    execution_timeout="30s",
)
def scenario_execute(input: ScenarioInput, ctx: Context) -> dict:
    """Execute one scenario for an audit run (fake target->auditor->judge).

    Idempotent: the final result row is upserted on (run_id, version_item_id),
    so re-execution after a retry or crash-recovery cannot duplicate it.
    """
    run_id = input.run_id
    version_item_id = input.version_item_id
    attempt = input.attempt

    # Durable progress event (stand-in for Postgres AuditEvent row).
    event_store.append_event(run_id, version_item_id, "scenario_attempted", {"attempt": attempt})

    # Simulate work; honour durable cancellation before doing it.
    if _is_cancelled(run_id):
        event_store.append_event(run_id, version_item_id, "scenario_skipped_cancelled")
        return {"status": "cancelled"}

    # Optional fault injection for the retry test: fail the first N EXECUTIONS.
    # Hatchet retries re-run the task with the SAME input (the `attempt` field
    # does NOT increment), so we must count how many times this version item has
    # already been attempted via durable events rather than trusting `attempt`.
    fail_times = int(os.environ.get("SPIKE_FAIL_TIMES", "0"))
    if fail_times > 0:
        executions = sum(
            1
            for e in event_store.list_events(run_id)
            if e["version_item_id"] == version_item_id and e["kind"] == "scenario_attempted"
        )
        if executions <= fail_times:
            raise RuntimeError(
                f"injected failure for {version_item_id} (execution {executions}/{fail_times})"
            )

    time.sleep(float(os.environ.get("SPIKE_SCENARIO_SECONDS", "0.05")))

    event_store.upsert_result(run_id, version_item_id, "completed", attempt)
    event_store.append_event(run_id, version_item_id, "scenario_completed", {"attempt": attempt})
    return {"status": "completed", "attempt": attempt}


@get_client().task(name="audit.run_finalize", input_validator=FinalizeInput, execution_timeout="30s")
def run_finalize(input: FinalizeInput, ctx: Context) -> dict:
    """Aggregate + finalize the run after all scenarios complete."""
    run_id = input.run_id

    # Version guard: worker must verify engine provenance against the frozen run.
    expected_version = input.simpleaudit_version
    expected_commit = input.git_commit
    if expected_version and expected_version != WORKER_SIMPLEAUDIT_VERSION:
        event_store.append_event(run_id, "_run", "run_failed", {"code": "SIMPLEAUDIT_VERSION_MISMATCH"})
        raise RuntimeError("SIMPLEAUDIT_VERSION_MISMATCH")
    if expected_commit and expected_commit != WORKER_GIT_COMMIT:
        event_store.append_event(run_id, "_run", "run_failed", {"code": "SIMPLEAUDIT_VERSION_MISMATCH"})
        raise RuntimeError("SIMPLEAUDIT_VERSION_MISMATCH")

    if _is_cancelled(run_id):
        event_store.append_event(run_id, "_run", "run_cancelled")
        return {"status": "cancelled"}

    total = event_store.count_results(run_id)
    event_store.append_event(run_id, "_run", "run_completed", {"scenarios": total})
    return {"status": "completed", "scenarios": total}


def build_worker() -> Worker:
    return Worker(
        name="spike-audit-worker",
        config=get_client().config,
        slot_config={"default": 4},
        labels={"pool": "cpu"},
        workflows=[scenario_execute, run_finalize],
    )


if __name__ == "__main__":
    event_store.init_db()
    worker = build_worker()
    print("Starting spike worker (embedded engine)...", flush=True)
    worker.start()
