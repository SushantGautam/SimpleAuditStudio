"""
Model Registry: nontechnical users pick a display name; the platform stores the
endpoint, model id, and a secret reference (env var name) — never the raw key.

Every audit snapshots the resolved config so a later change to an endpoint or
its parameters cannot alter what an old audit used.
"""

import os
from typing import Any, Dict, List, Optional

from . import db


def add_endpoint(
    display_name: str,
    provider: str,
    base_url: str,
    model_id: str,
    capabilities: Optional[Dict[str, Any]] = None,
    default_parameters: Optional[Dict[str, Any]] = None,
    secret_reference: Optional[str] = None,
    enabled: bool = True,
) -> int:
    return db.execute(
        """INSERT INTO model_endpoint
           (display_name, provider, base_url, model_id, capabilities,
            default_parameters, secret_reference, enabled, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            display_name,
            provider,
            base_url,
            model_id,
            db.dumps(capabilities),
            db.dumps(default_parameters),
            secret_reference,
            1 if enabled else 0,
            db._now(),
        ),
    )


def list_endpoints(enabled_only: bool = False) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM model_endpoint"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY display_name"
    rows = db.q(sql)
    for r in rows:
        r["capabilities"] = db.loads(r["capabilities"], {})
        r["default_parameters"] = db.loads(r["default_parameters"], {})
    return rows


def get_endpoint(endpoint_id: int) -> Optional[Dict[str, Any]]:
    row = db.q1("SELECT * FROM model_endpoint WHERE id=?", (endpoint_id,))
    if not row:
        return None
    row["capabilities"] = db.loads(row["capabilities"], {})
    row["default_parameters"] = db.loads(row["default_parameters"], {})
    return row


def resolve_secret(secret_reference: Optional[str]) -> Optional[str]:
    """Look up the actual API key from the environment by the stored reference."""
    if not secret_reference:
        return None
    return os.environ.get(secret_reference)


def snapshot_for_audit(endpoint_id: int) -> Dict[str, Any]:
    """Frozen, self-contained config for one role of an audit. The resolved key
    is included here (in-process only) so the worker can build its client; it is
    NOT persisted into the run's public snapshot."""
    ep = get_endpoint(endpoint_id)
    if not ep:
        raise ValueError(f"model endpoint {endpoint_id} not found")
    return {
        "endpoint_id": endpoint_id,
        "display_name": ep["display_name"],
        "provider": ep["provider"],
        "base_url": ep["base_url"],
        "model_id": ep["model_id"],
        "default_parameters": ep["default_parameters"],
        "secret_reference": ep["secret_reference"],
        "api_key": resolve_secret(ep["secret_reference"]),
    }
