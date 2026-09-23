"""Spike driver: proves the durable-job acceptance criteria end to end.

Each check maps to a non-negotiable criterion in docs/job-system-spike.md. The
driver runs against an embedded Hatchet engine + worker in-process, using the
SQLite event store as the durable AuditEvent stand-in.

Run:  python -m spike.run_spike
Exit code 0 = all checks passed; non-zero = at least one failed.
"""
from __future__ import annotations

import os
import sys
import threading
import time

# Isolate spike state before importing the worker (which builds the client).
os.environ.setdefault("SPIKE_EVENT_DB", "spike/events.sqlite3")
os.environ.setdefault("SPIKE_EMBEDDED_PG_DIR", "spike/.embedded-pg")
os.environ.setdefault("SPIKE_ENGINE_VERSION", "0.1.0")
os.environ.setdefault("SPIKE_ENGINE_GIT_COMMIT", "deadbeef")

from hatchet_sdk import Worker  # noqa: E402

from . import event_store  # noqa: E402
from .worker import FinalizeInput, ScenarioInput, get_client, scenario_execute, run_finalize  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _wait_for(predicate, timeout: float = 60.0, interval: float = 0.25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def main() -> int:
    event_store.init_db()
    event_store.reset()

    # Single shared embedded client: the worker listens on it and we submit to it.
    hatchet = get_client()
    worker = Worker(
        name="spike-audit-worker",
        config=hatchet.config,
        slot_config={"default": 4},
        labels={"pool": "cpu"},
        workflows=[scenario_execute, run_finalize],
    )
    # Worker.start() blocks (run_forever), so run it in a daemon thread and drive
    # the checks from the main thread.
    worker_thread = threading.Thread(target=worker.start, daemon=True)
    worker_thread.start()
    time.sleep(3)  # give the worker time to register with the engine

    try:
        # ------------------------------------------------------------------
        # Check 1+2: persistence & separation — submit a run, let the separate
        # worker process execute it, and confirm durable progress appears.
        # ------------------------------------------------------------------
        run_id = "run-1"
        items = ["item-a", "item-b", "item-c"]
        for item in items:
            scenario_execute.run_no_wait(ScenarioInput(run_id=run_id, version_item_id=item, attempt=1))

        def all_completed():
            return all(event_store.get_result(run_id, i) for i in items)

        ok = _wait_for(all_completed, timeout=90)
        check("persistence: scenarios executed by separate worker", ok,
              f"{sum(1 for i in items if event_store.get_result(run_id, i))}/{len(items)} results")

        # Progress events are durable and replayable from Last-Event-ID.
        events = event_store.list_events(run_id, after_id=0)
        kinds = {e["kind"] for e in events}
        check("progress: durable events written", {"scenario_attempted", "scenario_completed"} <= kinds,
              f"kinds={sorted(kinds)}")
        first_id = events[0]["id"] if events else 0
        replay = event_store.list_events(run_id, after_id=first_id)
        check("progress: SSE-style replay from Last-Event-ID", len(replay) == len(events) - 1,
              f"total={len(events)} after_first={len(replay)}")

        # Finalize the run (aggregation step).
        run_finalize.run_no_wait(FinalizeInput(
            run_id=run_id,
            simpleaudit_version=os.environ["SPIKE_ENGINE_VERSION"],
            git_commit=os.environ["SPIKE_ENGINE_GIT_COMMIT"],
        ))
        check("finalize: run completed event", _wait_for(
            lambda: any(e["kind"] == "run_completed" for e in event_store.list_events(run_id)), timeout=60),
            "")

        # ------------------------------------------------------------------
        # Check 3: idempotency — re-execute every scenario; final result count
        # must stay exactly 3 (no duplicate rows).
        # ------------------------------------------------------------------
        before = event_store.count_results(run_id)
        for item in items:
            scenario_execute.run_no_wait(ScenarioInput(run_id=run_id, version_item_id=item, attempt=2))
        _wait_for(lambda: all(
            (event_store.get_result(run_id, i) or {}).get("attempts", 0) >= 2 for i in items), timeout=90)
        after = event_store.count_results(run_id)
        check("idempotency: no duplicate final results on re-execution", before == after == 3,
              f"before={before} after={after}")

        # ------------------------------------------------------------------
        # Check 4: retry — a task that fails twice then succeeds must complete
        # via Hatchet retries (retries=2 on the task).
        # ------------------------------------------------------------------
        os.environ["SPIKE_FAIL_TIMES"] = "2"
        retry_run = "run-retry"
        scenario_execute.run_no_wait(ScenarioInput(run_id=retry_run, version_item_id="r1", attempt=1))
        retried_ok = _wait_for(lambda: event_store.get_result(retry_run, "r1"), timeout=120)
        res = event_store.get_result(retry_run, "r1") or {}
        check("retry: transient failures recovered via retry policy",
              retried_ok and res.get("status") == "completed",
              f"result={res}")
        os.environ["SPIKE_FAIL_TIMES"] = "0"

        # ------------------------------------------------------------------
        # Check 5: cancellation is durable — request cancel, then remaining
        # scenarios observe it from the store (not memory).
        # ------------------------------------------------------------------
        cancel_run = "run-cancel"
        event_store.append_event(cancel_run, "_run", "run_cancel_requested")
        for item in ["c1", "c2"]:
            scenario_execute.run_no_wait(ScenarioInput(run_id=cancel_run, version_item_id=item, attempt=1))
        # Wait specifically for BOTH scenarios to record their skip event. A loose
        # total-event-count predicate fires too early (the pre-seeded cancel request
        # plus the first scenario_attempted already reach 2 before any skip is written).
        _wait_for(
            lambda: sum(
                1 for e in event_store.list_events(cancel_run)
                if e["kind"] == "scenario_skipped_cancelled"
            ) == 2,
            timeout=60,
        )
        skipped = [e for e in event_store.list_events(cancel_run) if e["kind"] == "scenario_skipped_cancelled"]
        no_results = event_store.count_results(cancel_run) == 0
        check("cancellation: durable flag prevents remaining work",
              len(skipped) == 2 and no_results,
              f"skipped={len(skipped)} results={event_store.count_results(cancel_run)}")

        # ------------------------------------------------------------------
        # Check 6: version guard — mismatched provenance fails the run.
        # ------------------------------------------------------------------
        ver_run = "run-version"
        run_finalize.run_no_wait(FinalizeInput(
            run_id=ver_run,
            simpleaudit_version="9.9.9",  # deliberately wrong
            git_commit="wrongcommit",
        ))
        mismatch = _wait_for(
            lambda: any(e["kind"] == "run_failed" and e["payload"].find("MISMATCH") >= 0
                        for e in event_store.list_events(ver_run)),
            timeout=60,
        )
        check("version guard: mismatch fails run with SIMPLEAUDIT_VERSION_MISMATCH", mismatch, "")

    finally:
        try:
            worker.exit_gracefully()
        except Exception:
            pass
        try:
            hatchet.stop_embedded()
        except Exception:
            pass

    # ----------------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------------
    print("\n=== SPIKE SUMMARY ===", flush=True)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}", flush=True)
    print(f"\n{passed}/{len(RESULTS)} checks passed", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
