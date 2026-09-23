# SimpleAudit Platform

A production-quality, self-hostable platform for running AI model audits using
the [SimpleAudit](https://github.com/kelkalot/simpleaudit) engine (Target →
Auditor → Judge). Organizations and researchers can clone, deploy, and run real
audits with reproducible, immutable experiment records.

## Architecture

```
Browser (vanilla-JS SPA)
  ↓
Django 5.2 / DRF API
  ↓
PostgreSQL 16 (source of truth)
  ├── Scenario Library (append-only versioning)
  ├── Model Registry (secret references, never raw keys)
  ├── Audit Runs (frozen reproducibility manifests)
  └── Durable Events (progress + results)
  ↓
Hatchet (durable job queue)
  ↓
Workers (CPU / GPU pools)
  ↓
SimpleAudit Engine (pinned git commit)
  Target → Auditor → Judge
```

Key properties:

- **Immutable audit inputs**: every AuditRun pins a ScenarioSetVersion,
  endpoint snapshots, and generation parameters at submission time. Editing
  scenarios or endpoints later never changes historical runs.
- **Secrets by reference**: model credentials are stored as environment-variable
  names (e.g. `TARGET_KEY`), resolved at execution time. Raw secrets never touch
  the database.
- **Durable progress**: structured events (queued → preparing → target_execution
  → auditing → judging → aggregation → completed/failed/cancelled) persist in
  PostgreSQL and survive restarts.
- **Nontechnical UI**: users pick models by name, select scenario sets, and watch
  live progress — no JSON, CLI, or queue internals exposed.

## Quick start (Docker Compose)

```bash
git clone <repo-url> simpleaudit-platform
cd simpleaudit-platform
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_* etc.
docker compose up -d
# Wait for health: curl http://localhost:8000/healthz
# Log in at http://localhost:8000 with your bootstrap admin credentials.
```

For local development without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=config.settings
export SIMPLEAUDIT_LOCAL_SQLITE=1  # dev only; production uses Postgres
python manage.py migrate
python manage.py bootstrap_admin
python manage.py runserver
```

## Running tests

```bash
# SQLite (fast, no external deps)
SIMPLEAUDIT_LOCAL_SQLITE=1 python manage.py test core

# PostgreSQL (requires a running instance)
POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
POSTGRES_USER=simpleaudit POSTGRES_PASSWORD=testpass123 \
POSTGRES_DB=simpleaudit python manage.py test core
```

62 tests cover: domain invariants, scenario versioning immutability, model
registry secret handling, audit run freeze, worker lifecycle, finalize ordering
guard, missing-key-as-failure, engine integration, API auth/RBAC, and the
purge management command.

## E2E smoke test

With the full Docker Compose stack running (including the `mock` profile):

```bash
python deploy/e2e_smoke.py http://localhost:8000
```

This creates a scenario, model endpoints, submits an audit run, polls events
until completion, and verifies the result row has a valid severity. Exits 0 on
pass, 1 on failure.

## Management commands

| Command | Purpose |
|---|---|
| `bootstrap_admin` | Create initial admin user + default project (idempotent) |
| `purge_test_data` | Delete E2E/smoke-test artifacts by name prefix (supports `--dry-run`) |

## Project structure

```
config/           Django settings, URLs, ASGI/WSGI
core/             Domain models, services, views, serializers, worker, engine
  management/     Management commands (bootstrap_admin, purge_test_data)
  tests/          62 tests (unit, integration, E2E smoke)
static/           Vanilla-JS SPA (app.js, app.css, favicon.svg)
templates/        index.html (SPA shell)
deploy/           Docker assets (mock server, E2E driver, postgres init)
docs/             Phase 0 SDLC deliverables + ADRs
app/              DEPRECATED prototype (reference only, do not extend)
```

## Documentation

- `AGENTS.md` — engineering mission and constraints
- `ROADMAP.md` — phased delivery plan
- `docs/product-requirements.md` — personas, workflows, acceptance criteria
- `docs/architecture.md` — system design, service boundaries, data flow
- `docs/domain-model.md` — entities, relationships, invariants
- `docs/threat-model.md` — STRIDE analysis, mitigations
- `docs/test-strategy.md` — test pyramid, coverage targets
- `docs/deployment.md` — Docker Compose, env vars, upgrades
- `docs/adr/` — Architecture Decision Records (001–006)

## Deprecated prototype

The `app/`, `run.py`, `seed.py`, and `data/` directories contain the original
FastAPI/SQLite prototype. They are retained for historical reference only and
must not be extended or used in production.

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
