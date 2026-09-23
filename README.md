# SimpleAudit Platform

This repository contains a **deprecated prototype** for the SimpleAudit Platform.

Do not extend the FastAPI/SQLite/in-process-queue code path as the production
system. The canonical production design is defined in:

- `AGENTS.md`
- `ROADMAP.md`
- `docs/product-requirements.md`
- `docs/architecture.md`
- `docs/domain-model.md`
- `docs/threat-model.md`
- `docs/test-strategy.md`
- `docs/deployment.md`
- `docs/adr/`

The production platform must use Django, PostgreSQL, a durable workflow/job
system such as Hatchet, object storage such as MinIO/S3, authentication/RBAC,
durable progress events, and observability. SQLite and in-process queues are
prototype-only substitutes and are explicitly rejected for the canonical
deployment.

## Prototype status

The current code under `app/`, `run.py`, `seed.py`, and `templates/` is useful
only as exploratory reference material for:

- domain naming
- scenario revision/version concepts
- reproducibility manifest shape
- comparison warning ideas
- SimpleAudit adapter behavior

It is not a portable reference implementation and must not be treated as an
acceptable production architecture.

## Prototype-to-production mapping

| Production component | Prototype artifact | Status |
|---|---|---|
| Django web/API | FastAPI in `app/api.py` | replace |
| PostgreSQL source of truth | SQLite in `data/platform.db` | replace |
| Durable workflow/job system | In-process queue in `app/queue.py` | replace |
| Separate CPU/GPU workers | Single process worker in `app/worker.py` | replace |
| Object storage artifacts | Local files under `data/` | replace |
| Authentication/RBAC/projects | None | add |
| Durable SSE event replay | Process-local subscribers | replace |
| Observability | Minimal logging | add |

### The key invariant (from the spec)
An `AuditRun` points at an **immutable `ScenarioSetVersion`**, never at a mutable
set. Editing scenarios creates a new revision; publishing creates a new version.
Neither ever touches data an existing audit depends on. Every run also snapshots
its target/auditor/judge config, so a later change to any model endpoint cannot
alter what an old audit used.

## Data model
```
Scenario            1 - N  ScenarioRevision        (immutable edits)
ScenarioSet         1 - N  ScenarioSetVersion      (immutable snapshots)
ScenarioSetVersion  N - N  ScenarioRevision        (via ..._item)
ModelEndpoint       (registry: display name -> endpoint + secret_reference)
AuditRun            -> pins one ScenarioSetVersion + frozen config snapshots
AuditRunScenario    per-scenario result rows
Comparison          saved comparisons
```

## Prototype quick start — do not use for production

This section documents the deprecated prototype only.

```bash
cd simpleaudit-platform

# 1. Configure the gateway key in .env
#    SIMULACHAT_API_KEY=sk-...

# 2. Seed the prototype model registry + import the safety pack as set v1
python3 seed.py

# 3. Run the prototype server
python3 run.py            # http://127.0.0.1:8321
```

Open http://127.0.0.1:8321, go to **New Audit**, pick a scenario set + models +
judge profile, and hit **Start Audit**. This prototype uses SQLite and an
in-process queue; it is not the canonical deployment.

The prototype prefers the local SimpleAudit checkout at `~/simpleaudit`
(v0.1.10); add it to `PYTHONPATH` if you move things.

## API (kept small, per the spec)
```
POST   /api/audits                     create + queue an audit
GET    /api/audits                     list (optional ?status=)
GET    /api/audits/{id}                detail + config snapshots + metrics
POST   /api/audits/{id}/cancel         cancel a running audit
POST   /api/audits/{id}/retry          re-run with identical frozen inputs
GET    /api/audits/{id}/events         SSE progress stream
GET    /api/audits/{id}/results        per-scenario results
GET    /api/audits/{id}/manifest       reproducibility manifest (JSON)
POST   /api/audits/compare             {run_ids:[..], only_identical_scenarios}
GET    /api/scenario-sets              list sets
GET    /api/scenario-sets/{id}/versions
GET    /api/scenario-set-versions/{id} version detail + frozen scenarios
POST   /api/scenario-sets/import?pack=safety&name=Safety
GET    /api/models                     enabled model endpoints
```

## Prototype capabilities — historical reference only
The prototype demonstrated:
- submission wizard
- basic immutable `AuditRun` concept
- process-local SSE progress
- cancel/retry behavior
- scenario revision/version concepts
- model registry with secret references
- per-role token accounting
- comparison warnings

These behaviors are inputs to the production design, not production-complete
features. The production roadmap in `ROADMAP.md` defines what must be rebuilt
and verified.

## Security note
The gateway API key lives in `.env` (gitignored) and is referenced in the DB only
by name (`secret_reference`), never stored raw. Do not commit real keys.
