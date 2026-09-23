# SimpleAudit Platform — Test Strategy

Status: Phase 0 draft for independent review  
Date: 2026-09-22  
Owner: QA / Verification role  
Principle: tests are designed independently from implementation and must verify observable invariants, not internal convenience.

## 1. Testing goals

The test suite must prove:

1. audits are reproducible from frozen inputs
2. scenario edits do not alter historical audits
3. jobs survive web/API restarts
4. workers can fail and recover without silent data loss
5. users cannot access unauthorized resources
6. secrets never leak into manifests/logs/API responses
7. progress is durable and replayable
8. comparisons warn on incompatible experiments
9. production deployment uses real PostgreSQL/workflow/object storage components
10. SimpleAudit scientific semantics are preserved

## 2. Test levels

### 2.1 Unit tests

Scope:

- domain services
- validation rules
- status transitions
- content hashing
- comparison compatibility logic
- secret redaction
- manifest construction

Requirements:

- fast
- deterministic
- no network calls unless mocked
- cover happy path and failure paths
- assert stable error codes where useful

### 2.2 Domain invariant tests

These are first-class tests, not optional integration extras.

Required scenarios:

#### Scenario version immutability

1. create scenario set v1
2. create audit using v1
3. edit scenario
4. publish v2
5. assert v1 content unchanged
6. assert audit manifest still references v1 hashes
7. assert results display v1 content

#### Audit config immutability

1. create model endpoint A
2. create audit using A
3. change endpoint A URL/parameters
4. assert audit snapshot remains original
5. assert new audits use updated endpoint
6. execute audit against mock provider that captures requests
7. assert executed request used frozen snapshot URL/parameters, not live endpoint values

#### Retry identity

1. create run
2. retry run
3. assert retry creates a new `AuditRun`
4. assert new run has same frozen inputs
5. assert new run has new execution ID
6. assert old run remains terminal and unchanged

#### Terminal state protection

1. complete a run
2. attempt invalid transition
3. assert rejected with stable error

### 2.3 Database tests

Scope:

- migrations apply cleanly from empty database
- migrations apply over previous release
- constraints reject invalid rows
- foreign keys enforced
- unique version identities enforced
- append-only tables cannot be mutated through service API
- transactional consistency between run creation and event emission

Tools:

- Django test database or dedicated Postgres service
- migration history tests
- raw SQL constraint tests where ORM hides behavior

### 2.4 Queue/worker tests

Required scenarios:

- queued job starts after worker available
- concurrency limit respected
- task retry on transient failure
- permanent failure marks run failed
- worker death causes visible failure/retry
- server restart resumes queued jobs
- cancellation prevents not-yet-started scenarios
- cancellation during run reaches `cancelled`
- cancellation requested while web/API is down still completes after restart
- duplicate task execution does not duplicate final result rows
- GPU-labeled job only runs on GPU-capable worker
- backpressure prevents unbounded queue growth
- graceful shutdown drains or safely parks active tasks
- job/run history remains queryable after completion/failure/cancellation

Acceptance evidence:

- test logs show expected task attempts
- DB state shows expected status/counters
- no orphaned running state after simulated crash

### 2.5 API tests

Scope:

- OpenAPI contract stability
- authentication required
- role permissions enforced
- input validation errors
- pagination
- SSE auth and replay
- artifact download authorization
- no secrets in responses
- project scoping

Required negative tests:

- viewer cannot submit audit
- auditor cannot manage users
- user in project A cannot read project B run
- SSE endpoint rejects unauthenticated request
- manifest endpoint omits raw API key
- model endpoint registration blocks disallowed SSRF targets

### 2.6 Browser E2E tests

Use Playwright against Docker Compose test environment.

Critical journeys:

1. deploy fresh stack
2. log in as admin
3. seed/import scenario set
4. register model endpoint with fake/mock provider for E2E
5. create audit
6. watch progress through stages
7. open completed results
8. download manifest
9. compare two runs
10. see warning when scenario versions differ
11. cancel a queued/running audit
12. retry a failed audit

E2E should use a deterministic mock model provider by default, plus at least one optional live-provider smoke test excluded from normal CI.

### 2.7 Restart/recovery tests

Required:

- kill web container while audit queued → job still exists and starts later
- kill worker while audit running → task fails/retries according to policy
- restart SSE client → receives missing events via `Last-Event-ID`
- reconnect SSE to a different web instance → replay from durable storage is complete
- cancel run while web/API is down → cancellation still reaches durable state after restart
- crash between artifact upload and DB write → retry/reconciliation does not corrupt final result
- restart object storage mount/path → artifacts remain accessible by URI/hash
- database backup/restore → historical audits remain queryable

### 2.8 Security tests

Automated checks:

- secret reference appears in manifest, raw key does not
- logs do not contain API key fixture value
- XSS payload in scenario title is escaped in UI
- SQL injection strings rejected/parameterized
- CSRF token required for browser mutations
- unauthorized object storage URL returns 403
- SSRF blocked for private IPs unless explicitly allowed
- dependency audit passes

Manual/security review checklist:

- threat model reviewed
- new endpoints mapped to trust boundaries
- admin actions logged
- error messages do not leak internals

### 2.9 Performance/load tests

Initial targets are provisional and must be revisited with real workloads:

- 10 concurrent small audits
- 100-scenario audit with bounded parallelism
- 1,000 queued jobs without memory exhaustion
- SSE reconnect storm does not degrade API
- DB query plans remain indexed for list/detail/events

Measure:

- p50/p95 API latency
- queue wait time
- worker CPU/GPU utilization
- token throughput
- failure/retry rates
- memory growth over long run

Do not optimize until baseline measurements exist.

### 2.10 Reproducibility/regression tests

Maintain fixtures:

- small scenario pack
- golden SimpleAudit outputs for mock provider
- expected severity counts
- expected manifest fields
- expected visualizer-compatible JSON structure

Run against:

- current SimpleAudit checkout
- pinned SimpleAudit version used by release

Required provenance assertions:

- manifest `simpleaudit_version` is non-null
- manifest `git_commit` is non-null for production runs
- worker fails with `SIMPLEAUDIT_VERSION_MISMATCH` if loaded package differs from manifest
- release artifact records the exact SimpleAudit commit used

Any semantic drift must be explicit and reviewed.

## 3. Test environments

### 3.1 Local development

- Docker Compose for Postgres/MinIO/Hatchet
- mock model provider
- seeded demo data
- fast unit/integration subset

### 3.2 CI

- lint/typecheck
- unit tests
- domain invariant tests
- API tests
- migration tests
- queue/worker tests with testcontainers or Compose
- Playwright E2E
- dependency audit
- build Docker images

### 3.3 Staging

- live or recorded model provider
- longer timeout
- failure injection
- backup/restore drill
- upgrade drill

## 4. Fixtures and mocks

Mock model provider requirements:

- deterministic responses by scenario tag
- can simulate latency
- can simulate transient 500/429
- can simulate timeout
- can simulate malformed JSON
- records requests for assertions

Never use the mock provider as evidence of real model safety conclusions. It is only for platform mechanics.

## 5. Quality gates

A pull request cannot be approved if it breaks:

- domain invariant tests
- migration tests
- security negative tests
- E2E critical journey
- OpenAPI contract without documented migration
- reproducibility manifest schema
- SimpleAudit compatibility fixtures

Release candidate requires:

- full CI green
- fresh deploy from clean state
- backup/restore test
- upgrade test from previous release
- independent reviewer sign-off
- documented known issues

## 6. Evidence standard

“Works in my browser” is not sufficient.

For each major claim, record:

- command executed
- environment/version
- relevant output
- database state assertion
- artifact hash if applicable
- screenshot/video for UI behavior
- trace/log correlation IDs for failures

Completion claims require fresh verification evidence.

## 7. Independent verification

QA role must independently verify implementation claims:

- rerun tests from clean checkout
- inspect migrations rather than trusting code comments
- attempt to break immutability through API
- attempt to access cross-project resources
- search logs/responses for secret fixture
- restart components during E2E
- compare manifest before/after scenario edits

Independent reviewer may reject “production ready” without evidence.
