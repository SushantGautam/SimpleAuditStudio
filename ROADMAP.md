# SimpleAudit Studio Roadmap

Status: implementation in progress after Phase 0 review  
Date: 2026-09-22

Current evidence:

- Phase 0 documents exist and were reviewed.
- Phase 1 foundation exists: Django project, Postgres settings, migrations, auth/projects, health/readiness, startup checks, Docker Compose, CI.
- Phase 2 scenario library domain exists with immutable revisions, ordered set versions, content hashes, APIs, and invariant tests.
- Phase 3 model registry and audit profiles exist with secret-reference-only storage and safe snapshot fields.
- Phase 5 freeze layer partially exists: `AuditRun` creation stores pinned scenario version, endpoint snapshots, generation parameters, and engine provenance.
- Phase 4 durable job spike is designed but not yet implemented; no real audit execution should be enabled until it passes.

This roadmap is gated. A phase is complete only when its exit criteria and the global definition of done are satisfied. “Works in my browser” is not sufficient.

## Phase 0 — Design and Review

Goal: agree on production architecture before implementation.

Deliverables:

- `docs/product-requirements.md`
- `docs/architecture.md`
- `docs/domain-model.md`
- `docs/threat-model.md`
- `docs/test-strategy.md`
- `docs/deployment.md`
- `docs/adr/001-web-framework.md`
- `docs/adr/002-database.md`
- `docs/adr/003-job-system.md`
- `docs/adr/004-scenario-versioning.md`
- `docs/adr/005-artifact-storage.md`
- `docs/adr/006-observability.md`
- `ROADMAP.md`

Exit criteria:

- independent reviewer has reviewed all documents
- blocking findings resolved or explicitly accepted with risk owner
- ADR 003 spike plan agreed
- MVP scope frozen

## Phase 1 — Production Foundation

Goal: replace POC runtime with canonical stack skeleton.

Work:

- Django project structure
- PostgreSQL settings and migrations
- Docker Compose: web, postgres, minio, hatchet-server, worker-cpu
- health endpoints
- structured logging
- auth/users/projects/RBAC baseline
- admin seed command
- CI lint/tests/migrations check

Exit criteria:

- fresh `docker compose up -d` starts cleanly
- migrations run from empty DB
- login and project scoping work
- `/healthz` and `/readyz` pass
- no SQLite in canonical path
- no in-process queue in canonical path

## Phase 2 — Scenario Library

Goal: make scenario versioning a first-class durable domain.

Work:

- Scenario/Revision/Set/SetVersion models
- content hashing
- publish workflow
- import/export
- history/diff UI
- API endpoints
- invariant tests

Exit criteria:

- editing scenario after audit does not alter historical version
- publish creates immutable ordered snapshot
- import/export round-trip preserves hash
- UI explains versions to nontechnical users
- database constraints prevent mutation/deletion of referenced revisions

## Phase 3 — Model Registry and Audit Profiles

Goal: let users select models without raw endpoint JSON.

Work:

- model endpoint registry
- secret references
- capability labels
- default generation parameters
- audit profiles
- SSRF policy
- validation endpoint
- frozen safe snapshots

Exit criteria:

- no raw secrets stored in DB
- audit manifest contains safe snapshot only
- invalid/private endpoints rejected according to policy
- user can create audit profile from UI
- model selection is understandable by nontechnical persona

## Phase 4 — Durable Job System Spike

Goal: prove Hatchet or replacement meets mandatory requirements.

Work:

- minimal `audit.run` workflow
- worker pool labels
- retry/timeout/cancellation
- idempotency key
- event publication
- restart recovery test
- concurrency limit test

Exit criteria:

- ADR 003 acceptance criteria all pass, including backpressure, graceful shutdown, job history, and durable cancellation
- worker death/restart recovers or marks failed safely
- cancellation stops remaining scenarios and survives web/API restart
- duplicate execution cannot corrupt results
- `AuditEvent` confirmed as primary SSE replay source
- decision recorded as accepted or replaced

If spike fails:

- choose alternative satisfying same checklist
- update ADR 003
- do not fall back to in-process queue

## Phase 5 — Audit Execution Vertical Slice

Goal: one real end-to-end audit through production components.

Work:

- create audit from UI
- freeze reproducibility manifest
- submit workflow
- execute scenarios via SimpleAudit adapter
- store per-scenario results
- upload artifacts to MinIO
- aggregate metrics
- mark completed/failed

Exit criteria:

- mock provider E2E passes
- live provider smoke test passes in staging
- result rows queryable
- artifact hash verified
- manifest matches executed inputs
- failure produces diagnostic state

## Phase 6 — Progress and Events

Goal: durable, reconnect-safe progress.

Work:

- `AuditEvent` table
- stage transitions
- counters
- SSE endpoint with `Last-Event-ID`
- UI progress panel
- cancellation/retry UX

Exit criteria:

- browser refresh does not lose progress
- server restart replays events
- slow consumer does not corrupt state
- terminal states are stable
- progress shows stages and counts, not only percentage

## Phase 7 — Results and Comparison

Goal: make audits interpretable and comparable safely.

Work:

- results dashboard
- severity distribution
- transcript viewer
- judge rationale view
- comparison selector
- compatibility warnings
- intersection mode
- export

Exit criteria:

- incompatible comparisons are clearly flagged
- identical-revision comparison works
- visualizer integration or equivalent is usable
- exports match stored data
- nontechnical user can interpret summary without JSON

## Phase 8 — Observability

Goal: make failures diagnosable.

Work:

- OTel instrumentation
- trace correlation IDs
- LLM call spans
- token/latency metrics
- core operational dashboards/alerts for queue, worker, API, and failures
- Langfuse integration optional
- redaction tests

Exit criteria:

- trace covers API → workflow → worker → target/auditor/judge
- logs join to traces
- no secrets in telemetry
- disabling optional Langfuse does not break audits
- core OTel tracing/metrics are sufficient for MVP diagnostics
- operator can diagnose a failed scenario from evidence

## Phase 9 — Security Hardening

Goal: validate threat mitigations.

Work:

- authorization matrix tests
- secret scanning
- SSRF tests
- upload/import validation
- rate limiting
- dependency/container scanning
- audit log review
- penetration-style manual checks

Exit criteria:

- no high-severity open findings without accepted risk
- cross-project access blocked
- secrets never appear in manifests/logs/artifacts
- malicious URL/import cases handled
- security documentation updated

## Phase 10 — Reliability and Load

Goal: prove durability under realistic stress.

Work:

- worker kill tests
- server restart tests
- concurrent audits
- long-running audit test
- backpressure test
- backup/restore drill
- upgrade/rollback drill

Exit criteria:

- no lost durable progress
- no corrupted terminal state
- backups restore historical audit + artifact
- load test meets documented thresholds
- failure modes produce actionable diagnostics

## Phase 11 — Documentation and Release Candidate

Goal: make the platform deployable by another organization.

Work:

- README quickstart
- operator guide
- user guide
- API reference
- troubleshooting
- release notes
- pinned images
- clean install script/compose file

Exit criteria:

- fresh machine deployment succeeds using docs only
- non-maintainer can run mock audit
- backup/restore documented and tested
- release candidate tagged
- independent reviewer signs off on production readiness evidence

## Explicit non-goals during roadmap

Do not introduce unless a later measured requirement forces it:

- Kubernetes
- Kafka
- Elasticsearch
- ClickHouse
- lakeFS
- service mesh
- microservice decomposition
- custom distributed consensus systems

## Decision gates

Before Phase 4 completion:

- confirm job system ADR

Before Phase 5 completion:

- confirm SimpleAudit adapter preserves scientific semantics

Before Phase 11:

- confirm all DoD items have evidence links
