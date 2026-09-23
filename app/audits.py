"""
AuditRun lifecycle: creation (with frozen config snapshots + reproducibility
manifest), listing, detail, results, and comparison.
"""

from typing import Any, Dict, List, Optional

from . import db, models, scenarios, worker


def _simpleaudit_version() -> str:
    try:
        from simpleaudit import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


def create_run(
    name: str,
    scenario_set_version_id: int,
    target_endpoint_id: int,
    auditor_endpoint_id: int,
    judge_endpoint_id: int,
    judge_name: str = "safety",
    max_turns: int = 2,
    created_by: Optional[str] = None,
) -> int:
    version = scenarios.get_version(scenario_set_version_id)
    if not version:
        raise ValueError(f"scenario set version {scenario_set_version_id} not found")

    target_cfg = models.snapshot_for_audit(target_endpoint_id)
    auditor_cfg = models.snapshot_for_audit(auditor_endpoint_id)
    judge_cfg = models.snapshot_for_audit(judge_endpoint_id)
    judge_cfg["judge_name"] = judge_name
    judge_cfg["max_turns"] = max_turns

    total = version["scenario_count"]
    run_id = db.execute(
        """INSERT INTO audit_run
           (name, created_by, status, queued_at, scenario_set_version_id,
            target_config_snapshot, auditor_config_snapshot, judge_config_snapshot,
            simpleaudit_version, total_scenarios, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            created_by,
            "queued",
            db._now(),
            scenario_set_version_id,
            db.dumps(_public(target_cfg)),
            db.dumps(_public(auditor_cfg)),
            db.dumps(judge_cfg),
            _simpleaudit_version(),
            total,
            db._now(),
        ),
    )
    worker.submit_run(run_id)
    return run_id


def _public(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot stored on the run: everything except the resolved secret."""
    c = dict(cfg)
    c.pop("api_key", None)
    return c


def list_runs(status: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM audit_run"
    params: tuple = ()
    if status:
        sql += " WHERE status=?"
        params = (status,)
    sql += " ORDER BY id DESC"
    rows = db.q(sql, params)
    for r in rows:
        r["summary_metrics"] = db.loads(r["summary_metrics"])
        r["progress"] = db.loads(r["progress"], {})
    return rows


def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    r = db.q1("SELECT * FROM audit_run WHERE id=?", (run_id,))
    if not r:
        return None
    r["target_config_snapshot"] = db.loads(r["target_config_snapshot"])
    r["auditor_config_snapshot"] = db.loads(r["auditor_config_snapshot"])
    r["judge_config_snapshot"] = db.loads(r["judge_config_snapshot"])
    r["summary_metrics"] = db.loads(r["summary_metrics"])
    r["progress"] = db.loads(r["progress"], {})
    return r


def get_results(run_id: int) -> List[Dict[str, Any]]:
    rows = db.q(
        "SELECT * FROM audit_run_scenario WHERE run_id=? ORDER BY id", (run_id,)
    )
    for r in rows:
        for k in ("issues_found", "positive_behaviors", "recommendations", "conversation", "judgment"):
            r[k] = db.loads(r[k], [] if k != "judgment" else {})
    return rows


def reproducibility_manifest(run_id: int) -> Dict[str, Any]:
    """The spec's downloadable provenance record for an audit."""
    r = get_run(run_id)
    if not r:
        raise ValueError(f"run {run_id} not found")
    version = scenarios.get_version(r["scenario_set_version_id"])
    return {
        "simpleaudit_version": r["simpleaudit_version"],
        "git_commit": r["git_commit"],
        "scenario_set": {
            "id": version["set_id"],
            "name": version["set_name"],
            "version": version["version"],
            "hash": version["content_hash"],
        },
        "target": _strip_secret(r["target_config_snapshot"]),
        "auditor": _strip_secret(r["auditor_config_snapshot"]),
        "judge": _strip_secret(r["judge_config_snapshot"]),
        "created_at": r["created_at"],
        "started_at": r["started_at"],
        "completed_at": r["finished_at"],
    }


def _strip_secret(cfg: Dict[str, Any]) -> Dict[str, Any]:
    c = dict(cfg)
    c.pop("api_key", None)
    return c


# --- comparison ------------------------------------------------------------

def compare(run_ids: List[int], only_identical: bool = False) -> Dict[str, Any]:
    runs = [get_run(rid) for rid in run_ids]
    cols = []
    for r in runs:
        m = r["summary_metrics"] or {}
        sc = m.get("severity_counts", {})
        cols.append(
            {
                "run_id": r["id"],
                "name": r["name"],
                "target": r["target_config_snapshot"].get("display_name"),
                "auditor": r["auditor_config_snapshot"].get("display_name"),
                "judge": r["judge_config_snapshot"].get("judge_name"),
                "scenario_version": scenarios.get_version(r["scenario_set_version_id"])["version"],
                "total": m.get("total"),
                "safe_rate": m.get("safe_rate"),
                "unsafe_rate": m.get("unsafe_rate"),
                "pass": sc.get("pass", 0),
                "low": sc.get("low", 0),
                "medium": sc.get("medium", 0),
                "high": sc.get("high", 0),
                "critical": sc.get("critical", 0),
                "error": sc.get("ERROR", 0),
            }
        )
    # Comparison validity warning: differing scenario versions.
    versions = {c["scenario_version"] for c in cols}
    warning = None
    if len(versions) > 1:
        warning = f"Scenario versions differ across runs: {sorted(versions)}"
    return {"columns": cols, "warning": warning, "only_identical_scenarios": only_identical}
