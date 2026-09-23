"""
SimpleAudit Platform — FastAPI application.

REST API (kept small per the spec) + SSE progress stream + a lightweight HTML
UI (no React monster). The existing SimpleAudit Visualizer is reused for deep
result analysis; this UI handles submission, queue state, and comparison.
"""

import asyncio
import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import audits, db, models, scenarios
from .queue import queue

BASE = Path(__file__).resolve().parent.parent
app = FastAPI(title="SimpleAudit Platform")


# --- startup ---------------------------------------------------------------

@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    queue.start()


# --- schemas ---------------------------------------------------------------

class CreateAudit(BaseModel):
    name: str
    scenario_set_version_id: int
    target_endpoint_id: int
    auditor_endpoint_id: int
    judge_endpoint_id: int
    judge_name: str = "safety"
    max_turns: int = 2


class CompareReq(BaseModel):
    run_ids: List[int]
    only_identical_scenarios: bool = False


# --- audits ----------------------------------------------------------------

@app.post("/api/audits")
def create_audit(body: CreateAudit):
    try:
        run_id = audits.create_run(
            name=body.name,
            scenario_set_version_id=body.scenario_set_version_id,
            target_endpoint_id=body.target_endpoint_id,
            auditor_endpoint_id=body.auditor_endpoint_id,
            judge_endpoint_id=body.judge_endpoint_id,
            judge_name=body.judge_name,
            max_turns=body.max_turns,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": run_id}


@app.get("/api/audits")
def list_audits(status: Optional[str] = None):
    return audits.list_runs(status)


@app.get("/api/audits/{run_id}")
def get_audit(run_id: int):
    r = audits.get_run(run_id)
    if not r:
        raise HTTPException(404, "not found")
    return r


@app.post("/api/audits/{run_id}/cancel")
def cancel_audit(run_id: int):
    ok = audits_cancel(run_id)
    return {"cancelled": ok}


def audits_cancel(run_id: int):
    from . import worker

    return worker.cancel_run(run_id)


@app.post("/api/audits/{run_id}/retry")
def retry_audit(run_id: int):
    from . import worker

    try:
        new_id = worker.retry_run(run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": new_id}


@app.get("/api/audits/{run_id}/results")
def audit_results(run_id: int):
    return audits.get_results(run_id)


@app.get("/api/audits/{run_id}/manifest")
def audit_manifest(run_id: int):
    return audits.reproducibility_manifest(run_id)


@app.get("/api/audits/{run_id}/events")
async def audit_events(run_id: int):
    """SSE stream of progress events for a running audit."""
    q = queue.subscribe(run_id)

    async def gen():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            queue.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/audits/compare")
def compare(body: CompareReq):
    return audits.compare(body.run_ids, body.only_identical_scenarios)


# --- scenario sets ---------------------------------------------------------

@app.get("/api/scenario-sets")
def list_sets():
    return scenarios.list_sets()


@app.get("/api/scenario-sets/{set_id}/versions")
def set_versions(set_id: int):
    return scenarios.list_versions(set_id)


@app.get("/api/scenario-set-versions/{version_id}")
def version_detail(version_id: int):
    v = scenarios.get_version(version_id)
    if not v:
        raise HTTPException(404, "not found")
    v["scenarios"] = scenarios.get_scenarios_for_version(version_id)
    return v


@app.post("/api/scenario-sets/import")
def import_pack(pack: str, name: Optional[str] = None):
    vid = scenarios.import_pack(pack, name)
    return {"version_id": vid}


# --- models ----------------------------------------------------------------

@app.get("/api/models")
def list_models():
    return models.list_endpoints(enabled_only=True)


# --- UI --------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "templates" / "index.html").read_text()


@app.get("/static/{path:path}")
def static(path: str):
    p = BASE / "static" / path
    if not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)
