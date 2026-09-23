"""
Scenario Library: scenarios, immutable revisions, sets, and set versions.

Implements the spec's versioning rule: every audit pins an immutable
ScenarioSetVersion. Editing a scenario creates a new revision; publishing a set
creates a new version. Neither ever mutates data an existing audit depends on.
"""

import hashlib
from typing import Any, Dict, List, Optional

from . import db


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return "sha256:" + h.hexdigest()[:16]


# --- Scenarios & revisions -------------------------------------------------

def upsert_scenario(key: str, title: str, category: Optional[str]) -> int:
    row = db.q1("SELECT id FROM scenario WHERE key = ?", (key,))
    if row:
        return row["id"]
    return db.execute(
        "INSERT INTO scenario (key, title, category, created_at) VALUES (?,?,?,?)",
        (key, title, category, db._now()),
    )


def create_revision(
    scenario_id: int,
    description: str,
    expected_behavior: Optional[List[str]] = None,
    test_prompt: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
) -> int:
    last = db.q1(
        "SELECT COALESCE(MAX(revision),0) AS r FROM scenario_revision WHERE scenario_id=?",
        (scenario_id,),
    )
    rev = last["r"] + 1
    content_hash = _hash(description or "", db.dumps(expected_behavior or []), test_prompt or "")
    return db.execute(
        """INSERT INTO scenario_revision
           (scenario_id, revision, description, expected_behavior, test_prompt, metadata,
            content_hash, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            scenario_id,
            rev,
            description,
            db.dumps(expected_behavior),
            test_prompt,
            db.dumps(metadata),
            content_hash,
            created_by,
            db._now(),
        ),
    )


def latest_revision(scenario_id: int) -> Optional[Dict[str, Any]]:
    return db.q1(
        "SELECT * FROM scenario_revision WHERE scenario_id=? ORDER BY revision DESC LIMIT 1",
        (scenario_id,),
    )


# --- Sets & versions -------------------------------------------------------

def create_set(name: str, description: Optional[str] = None) -> int:
    return db.execute(
        "INSERT INTO scenario_set (name, description, created_at) VALUES (?,?,?)",
        (name, description, db._now()),
    )


def publish_version(set_id: int, created_by: Optional[str] = None) -> int:
    """Snapshot the latest revision of every scenario currently in this set into
    a new immutable version. If the set has no items yet, it is empty."""
    last = db.q1(
        "SELECT COALESCE(MAX(version),0) AS v FROM scenario_set_version WHERE set_id=?",
        (set_id,),
    )
    version = last["v"] + 1

    # Determine which scenarios belong to this set from its most recent version
    # (or all scenarios if none exists yet).
    prev = db.q1(
        "SELECT id FROM scenario_set_version WHERE set_id=? ORDER BY version DESC LIMIT 1",
        (set_id,),
    )
    if prev:
        scenario_ids = [
            r["scenario_id"]
            for r in db.q(
                "SELECT scenario_id FROM scenario_set_version_item WHERE version_id=?",
                (prev["id"],),
            )
        ]
    else:
        scenario_ids = [r["id"] for r in db.q("SELECT id FROM scenario ORDER BY id")]

    vid = db.execute(
        """INSERT INTO scenario_set_version
           (set_id, version, scenario_count, content_hash, created_by, created_at)
           VALUES (?,?,?,?,?,?)""",
        (set_id, version, len(scenario_ids), "pending", created_by, db._now()),
    )

    hashes = []
    for pos, sid in enumerate(scenario_ids):
        rev = latest_revision(sid)
        if not rev:
            continue
        db.execute(
            """INSERT INTO scenario_set_version_item
               (version_id, scenario_id, revision_id, position) VALUES (?,?,?,?)""",
            (vid, sid, rev["id"], pos),
        )
        hashes.append(rev["content_hash"])

    content_hash = _hash(*hashes)
    db.execute(
        "UPDATE scenario_set_version SET content_hash=?, scenario_count=? WHERE id=?",
        (content_hash, len(hashes), vid),
    )
    return vid


def get_scenarios_for_version(version_id: int) -> List[Dict[str, Any]]:
    """Return the frozen scenario list for a version, ready to feed ModelAuditor."""
    rows = db.q(
        """SELECT s.key, s.title, sr.description, sr.expected_behavior,
                  sr.test_prompt, sr.metadata
           FROM scenario_set_version_item i
           JOIN scenario s ON s.id = i.scenario_id
           JOIN scenario_revision sr ON sr.id = i.revision_id
           WHERE i.version_id = ?
           ORDER BY i.position""",
        (version_id,),
    )
    out = []
    for r in rows:
        out.append(
            {
                "name": r["title"],
                "description": r["description"] or "",
                "expected_behavior": db.loads(r["expected_behavior"]),
                "test_prompt": r["test_prompt"],
                "metadata": db.loads(r["metadata"], {}),
            }
        )
    return out


def list_sets() -> List[Dict[str, Any]]:
    return db.q(
        """SELECT st.*,
                  (SELECT MAX(v.version) FROM scenario_set_version v WHERE v.set_id=st.id) AS latest_version,
                  (SELECT v.scenario_count FROM scenario_set_version v
                    WHERE v.set_id=st.id ORDER BY v.version DESC LIMIT 1) AS scenario_count
           FROM scenario_set st ORDER BY st.name"""
    )


def list_versions(set_id: int) -> List[Dict[str, Any]]:
    return db.q(
        "SELECT * FROM scenario_set_version WHERE set_id=? ORDER BY version DESC",
        (set_id,),
    )


def get_version(version_id: int) -> Optional[Dict[str, Any]]:
    return db.q1(
        """SELECT v.*, st.name AS set_name FROM scenario_set_version v
           JOIN scenario_set st ON st.id = v.set_id WHERE v.id=?""",
        (version_id,),
    )


# --- Import built-in packs as a set ----------------------------------------

def import_pack(pack_name: str, set_name: Optional[str] = None) -> int:
    """Import a simpleaudit built-in scenario pack as a new set + version 1."""
    from simpleaudit import get_scenarios

    pack = get_scenarios(pack_name)
    set_id = create_set(set_name or pack_name, f"Imported from simpleaudit pack '{pack_name}'")
    for sc in pack:
        key = f"{pack_name}:{sc['name']}"
        sid = upsert_scenario(key, sc["name"], sc.get("category"))
        create_revision(
            sid,
            sc.get("description", ""),
            sc.get("expected_behavior"),
            sc.get("test_prompt"),
            sc.get("metadata"),
            created_by="import",
        )
    return publish_version(set_id, created_by="import")
