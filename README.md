# SimpleAudit Studio

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
git clone <repo-url> simpleaudit-studio
cd simpleaudit-studio
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_* etc.
docker compose up -d
# Wait for health: curl http://localhost:8000/healthz
# Log in at http://localhost:8000 with your bootstrap admin credentials.
```

A `Makefile` wraps the common tasks: `make docker-up`, `make local-setup`,
`make local-web`, `make local-worker`, `make test`, `make e2e` — run
`make help` for the full list.

For local development without Docker (web + worker as plain processes):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.local.example .env   # SQLite + localhost defaults; edit as needed
python manage.py migrate
python manage.py bootstrap_platform
python manage.py runserver
```

`manage.py` loads `.env` automatically (python-dotenv); real environment
variables always take precedence.

### Local development with real audit execution (partial Docker)

Running audits requires the durable job queue (Hatchet) and the SimpleAudit
engine. The "partial Docker" pattern keeps Postgres + Hatchet in containers
while web and worker run on your machine:

```bash
# 1. Queue infrastructure only (Postgres + Hatchet server)
docker compose up -d postgres hatchet-server

# 2. Give the local worker the Hatchet worker token
docker compose cp hatchet-server:/config/authdisabled-token ./hatchet-token

# 3. In .env (from .env.local.example):
#    SIMPLEAUDIT_LOCAL_SQLITE=1            (domain DB on SQLite)
#    HATCHET_SERVER_URL=http://localhost:8888
#    HATCHET_GRPC_URL=localhost:7077
#    HATCHET_TOKEN_FILE=./hatchet-token
#    (no SimpleAudit config needed — see below)

# 4. Terminal A: web server
python manage.py runserver

# 5. Terminal B: worker (executes audits via the engine)
python manage.py run_worker --pool cpu
```

The Hatchet dashboard is at http://localhost:8888. The SimpleAudit engine is a
normal pip dependency pinned in `requirements.txt`; its version + optional git
commit are read from the installed package metadata automatically
(`infra/simpleaudit_package.py`). To develop against an unmerged revision, create
a gitignored `simpleaudit-dependency.yaml` at the project root with a single
`git_ref:` key — do not edit `requirements.txt`.

## Running tests

```bash
# SQLite (fast, no external deps) — 93 tests
SIMPLEAUDIT_LOCAL_SQLITE=1 python manage.py test infra

# PostgreSQL (requires a running instance)
POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
POSTGRES_USER=simpleaudit POSTGRES_PASSWORD=testpass123 \
POSTGRES_DB=simpleaudit python manage.py test infra
```

The suite covers: domain invariants, scenario versioning immutability, model
registry secret handling, audit run freeze, worker lifecycle, finalize ordering
guard, missing-key-as-failure, engine integration, API auth/RBAC, SSE events,
comparison engine, and an all-pages smoke test (factory-boy fixtures).

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
| `bootstrap_platform` | Create initial admin user + default project (idempotent) |
| `run_worker` | Start a Hatchet worker pool (`--pool cpu\|gpu`) |
| `import_simpleaudit_packs` | Import SimpleAudit scenario packs into the library |
| `purge_test_data` | Delete E2E/smoke-test artifacts by name prefix (supports `--dry-run`) |

## Project structure

```
config/           Django settings, URLs, ASGI/WSGI
accounts/         Users, projects, memberships (bootstrap, RBAC)
scenarios/        Scenario, ScenarioRevision, ScenarioSet, ScenarioSetVersion
model_registry/   ModelEndpoint (secret references), AuditProfile
audits/           AuditRun, results, events, comparison engine, services
infra/            Engine integration, Hatchet worker, UI views, middleware
  management/     Management commands (bootstrap_platform, run_worker, ...)
  tests/          92 tests (unit, integration, all-pages smoke)
static/           UI assets
templates/        Django templates (dashboard, queue, audit detail, ...)
deploy/           Docker assets (mock server, E2E driver, postgres init)
e2e/              Browser E2E driver
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
cd simpleaudit-studio

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
