"""
SimpleAudit Worker: executes one AuditRun.

Flow (from the spec):
    load frozen configuration
        -> load scenario snapshot (pinned ScenarioSetVersion)
        -> target inference
        -> auditor
        -> judge
        -> aggregate
        -> persist results
        -> completed

The three LLM roles are driven by simpleaudit.ModelAuditor, which already
implements target/auditor/judge orchestration, retries, and JSON parsing. We
build it from the run's frozen config snapshots so a later change to any model
endpoint cannot alter what this audit used.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

# Prefer the local SimpleAudit checkout (v0.1.10) over any older installed copy.
_SA = Path.home() / "simpleaudit"
if (_SA / "simpleaudit").is_dir():
    sys.path.insert(0, str(_SA))

from . import db, models, scenarios  # noqa: E402
from .queue import queue  # noqa: E402


def _client_kwargs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Map a frozen role config onto ModelAuditor constructor args."""
    return {
        "model": cfg["model_id"],
        "provider": cfg["provider"],
        "api_key": cfg.get("api_key") or models.resolve_secret(cfg.get("secret_reference")),
        "base_url": cfg["base_url"],
    }


async def run_audit(run_id: int) -> None:
    run = db.q1("SELECT * FROM audit_run WHERE id=?", (run_id,))
    if not run:
        return

    # --- mark running ------------------------------------------------------
    db.execute(
        "UPDATE audit_run SET status='running', started_at=?, current_stage='loading' WHERE id=?",
        (db._now(), run_id),
    )
    queue.publish(run_id, {"type": "stage", "stage": "loading"})

    # --- load frozen config + scenario snapshot ---------------------------
    target_cfg = db.loads(run["target_config_snapshot"])
    auditor_cfg = db.loads(run["auditor_config_snapshot"])
    judge_cfg = db.loads(run["judge_config_snapshot"])
    version = scenarios.get_version(run["scenario_set_version_id"])
    scenario_list = scenarios.get_scenarios_for_version(run["scenario_set_version_id"])

    total = len(scenario_list)
    db.execute(
        "UPDATE audit_run SET total_scenarios=? WHERE id=?",
        (total, run_id),
    )

    # Build the auditor from the frozen snapshots. Judge config name drives the
    # named judge; explicit model/provider/key/url come from the snapshots.
    from simpleaudit import ModelAuditor

    t = _client_kwargs(target_cfg)
    j = _client_kwargs(judge_cfg)
    a = _client_kwargs(auditor_cfg)

    auditor = ModelAuditor(
        model=t["model"],
        provider=t["provider"],
        api_key=t.get("api_key"),
        base_url=t.get("base_url"),
        judge_model=j["model"],
        judge_provider=j["provider"],
        judge_api_key=j.get("api_key"),
        judge_base_url=j.get("base_url"),
        auditor_model=a["model"],
        auditor_provider=a["provider"],
        auditor_api_key=a.get("api_key"),
        auditor_base_url=a.get("base_url"),
        judge=judge_cfg.get("judge_name"),  # named judge config (e.g. "safety")
        verbose=False,
        show_progress=False,
        max_turns=judge_cfg.get("max_turns", 2),
    )

    # --- run target->auditor->judge over all scenarios --------------------
    queue.publish(run_id, {"type": "stage", "stage": "audit"})
    results = await auditor.run_async(
        scenario_list,
        max_turns=judge_cfg.get("max_turns", 2),
        language="English",
        max_workers=4,
    )

    # --- persist per-scenario results -------------------------------------
    queue.publish(run_id, {"type": "stage", "stage": "persisting"})
    artifact_path = f"data/run_{run_id}_results.json"
    results.save(artifact_path)

    successful = failed = 0
    for r in results.results:
        sev = r.severity
        if sev == "ERROR":
            failed += 1
            status = "error"
        else:
            successful += 1
            status = "done"
        db.execute(
            """INSERT INTO audit_run_scenario
               (run_id, scenario_name, severity, issues_found, positive_behaviors,
                summary, recommendations, conversation, judgment,
                target_tokens, auditor_tokens, judge_tokens, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                r.scenario_name,
                sev,
                db.dumps(r.issues_found),
                db.dumps(r.positive_behaviors),
                r.summary,
                db.dumps(r.recommendations),
                db.dumps(r.conversation),
                db.dumps(r.judgment),
                r.target_input_tokens + r.target_output_tokens,
                r.auditor_input_tokens + r.auditor_output_tokens,
                r.judge_input_tokens + r.judge_output_tokens,
                status,
            ),
        )

    # --- aggregate metrics -------------------------------------------------
    from collections import Counter

    sev_counts = Counter(r.severity for r in results.results)
    safe = sev_counts.get("pass", 0) + sev_counts.get("low", 0)
    unsafe = sev_counts.get("critical", 0) + sev_counts.get("high", 0)
    n = len(results.results) or 1
    summary_metrics = {
        "total": len(results.results),
        "severity_counts": dict(sev_counts),
        "safe_rate": round(safe / n, 3),
        "unsafe_rate": round(unsafe / n, 3),
        "target_tokens": results.total_target_input_tokens + results.total_target_output_tokens,
        "auditor_tokens": results.total_auditor_input_tokens + results.total_auditor_output_tokens,
        "judge_tokens": results.total_judge_input_tokens + results.total_judge_output_tokens,
    }

    db.execute(
        """UPDATE audit_run
           SET status='completed', finished_at=?, completed_scenarios=?, failed_scenarios=?,
               current_stage='completed', summary_metrics=?, artifact_uri=?
           WHERE id=?""",
        (
            db._now(),
            successful,
            failed,
            db.dumps(summary_metrics),
            artifact_path,
            run_id,
        ),
    )
    queue.publish(run_id, {"type": "progress", **summary_metrics})
    queue.publish(run_id, {"type": "done"})


# --- public entry points used by the API -----------------------------------

def submit_run(run_id: int) -> str:
    job_id = queue.submit(run_id, run_audit)
    db.execute("UPDATE audit_run SET worker_job_id=? WHERE id=?", (job_id, run_id))
    return job_id


def cancel_run(run_id: int) -> bool:
    run = db.q1("SELECT worker_job_id FROM audit_run WHERE id=?", (run_id,))
    if not run or not run["worker_job_id"]:
        return False
    ok = queue.cancel(run["worker_job_id"])
    if ok:
        db.execute(
            "UPDATE audit_run SET status='cancelled', finished_at=? WHERE id=?",
            (db._now(), run_id),
        )
    return ok


def retry_run(run_id: int) -> int:
    """Create a fresh queued run that reuses the original's frozen config and
    pinned scenario version (reproducibility: same inputs, new execution)."""
    src = db.q1("SELECT * FROM audit_run WHERE id=?", (run_id,))
    if not src:
        raise ValueError(f"run {run_id} not found")
    new_id = db.execute(
        """INSERT INTO audit_run
           (name, created_by, status, queued_at, scenario_set_version_id,
            target_config_snapshot, auditor_config_snapshot, judge_config_snapshot,
            simpleaudit_version, git_commit, total_scenarios, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"{src['name']} (retry)",
            src["created_by"],
            "queued",
            db._now(),
            src["scenario_set_version_id"],
            src["target_config_snapshot"],
            src["auditor_config_snapshot"],
            src["judge_config_snapshot"],
            src["simpleaudit_version"],
            src["git_commit"],
            src["total_scenarios"],
            db._now(),
        ),
    )
    submit_run(new_id)
    return new_id
