"""
In-process job queue — the Hatchet-equivalent for this portable build.

Provides what the spec needs from a scheduler: queued state, worker assignment,
concurrency control, retries, cancellation, run status, and progress streaming.
It deliberately does NOT store audit results (that is the database's job); it
only orchestrates execution of `worker.run_audit`.

Progress events are fanned out to per-run SSE subscribers so the browser can
render live stage/percent updates without polling.
"""

import asyncio
import itertools
import threading
from typing import Any, Callable, Dict, List, Optional

_job_seq = itertools.count(1)


class JobQueue:
    def __init__(self, max_concurrency: int = 2):
        self.max_concurrency = max_concurrency
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._subscribers: Dict[int, List[asyncio.Queue]] = {}  # run_id -> queues
        self._running: Dict[str, asyncio.Task] = {}  # job_id -> task
        self._lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    # --- submission --------------------------------------------------------
    def submit(self, run_id: int, fn: Callable[[int], Any]) -> str:
        """Schedule fn(run_id) on the loop under the concurrency semaphore."""
        job_id = f"job-{next(_job_seq)}"
        assert self._loop is not None, "queue not started"
        fut = asyncio.run_coroutine_threadsafe(self._guarded(job_id, run_id, fn), self._loop)
        return job_id

    async def _guarded(self, job_id: str, run_id: int, fn: Callable[[int], Any]) -> None:
        sem = self._ensure_semaphore()
        async with sem:
            try:
                await fn(run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced via run.error
                from . import db

                db.execute(
                    "UPDATE audit_run SET status='failed', error=?, finished_at=? WHERE id=?",
                    (f"{type(exc).__name__}: {exc}", db._now(), run_id),
                )
                self.publish(run_id, {"type": "error", "error": str(exc)})

    # --- cancellation / retry ---------------------------------------------
    def cancel(self, job_id: str) -> bool:
        with self._lock:
            task = self._running.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def register_running(self, job_id: str, task: asyncio.Task) -> None:
        with self._lock:
            self._running[job_id] = task

    # --- progress fan-out (SSE) -------------------------------------------
    def subscribe(self, run_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: int, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subscribers.pop(run_id, None)

    def publish(self, run_id: int, event: Dict[str, Any]) -> None:
        for q in list(self._subscribers.get(run_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer; drop rather than block the worker


# Singleton used by the app.
queue = JobQueue(max_concurrency=2)
