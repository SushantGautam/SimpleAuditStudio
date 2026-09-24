# SimpleAudit Studio — Threat Model

Status: Phase 0 draft for independent review  
Date: 2026-09-22  
Owner: Security role  
Method: STRIDE-inspired review of deployment, API, data, execution, and supply chain

## 1. Trust boundaries

### 1.1 Browser user

Trusted only after authentication. May still attempt:

- horizontal privilege escalation
- vertical privilege escalation
- injection through forms
- excessive resource consumption
- access to other users’ audits if multi-user

### 1.2 Django Web/API

Trusted application code. Must enforce:

- authentication
- authorization
- input validation
- output encoding
- rate limiting
- secret non-disclosure

### 1.3 PostgreSQL

Trusted primary datastore. Must protect:

- confidentiality of audit content
- integrity of immutable revisions
- availability of job state

### 1.4 Workflow/queue

Trusted internal infrastructure. Must protect:

- job payloads from tampering
- worker credentials from exposure
- replay/duplicate execution

### 1.5 Workers

Trusted execution environment with elevated access to secrets. Must:

- resolve secrets only at runtime
- avoid logging prompts/transcripts/secrets
- write artifacts with controlled permissions
- not expose public network ports

### 1.6 Model endpoints

Untrusted external or local network services. May:

- leak prompts if compromised
- behave maliciously or unpredictably
- be abused for SSRF if user-controlled
- expose sensitive metadata in errors

### 1.7 Object storage

Trusted storage but potentially accessible by multiple components. Must enforce:

- private buckets
- signed URLs
- object-level authorization
- integrity hashes

## 2. Assets

| Asset | Confidentiality | Integrity | Availability |
|---|---:|---:|---:|
| User credentials | high | high | high |
| Model API secrets | critical | critical | high |
| Scenario content | high | high | medium |
| Audit transcripts | high | high | medium |
| Judge rationales | high | high | medium |
| Audit results/metrics | medium-high | high | high |
| Reproducibility manifests | medium | critical | high |
| Worker logs | medium | medium | medium |
| Queue state | medium | high | high |
| Software dependencies | low | critical | high |

## 3. Threats and mitigations

### 3.1 Spoofing

Threats:

- attacker impersonates user
- forged API requests
- spoofed worker submitting fake results
- DNS/network spoofing to model endpoint

Mitigations:

- HTTPS/TLS in deployment
- session cookies with CSRF protection
- server-side authorization
- workflow worker authentication
- signed/internal network communication where feasible
- verify artifact hashes
- pin/trust model endpoint configuration through admin-only settings

### 3.2 Tampering

Threats:

- edit scenario revision used by historical audit
- modify audit config snapshot after submission
- alter result rows after completion
- replace artifact file
- manipulate progress events

Mitigations:

- append-only revision/version tables
- no public mutation endpoints for pinned entities
- content hashes
- DB constraints and service-layer immutability
- artifact SHA-256 recorded at upload
- event sequence numbers
- audit log for admin changes
- integration tests proving historical run unchanged after edits

### 3.3 Repudiation

Threats:

- user denies creating/canceling audit
- admin changes model endpoint without trace
- secret rotated without record

Mitigations:

- `created_by`, timestamps
- audit log table
- immutable run manifest
- administrative action logging
- exportable logs

### 3.4 Information disclosure

Threats:

- API key leaked in manifest/log/error
- transcript exposed to unauthorized user
- SSE stream accessed without auth
- object storage public bucket
- dependency package exfiltrates env vars

Mitigations:

- store secret references only
- redact secrets in logs
- authorize every API/SSE/artifact request
- private object storage + signed URLs
- dependency pinning and review
- no raw secrets in browser storage
- error responses do not dump stack traces in production

### 3.5 Denial of service

Threats:

- submit huge scenario set
- unbounded concurrent LLM calls
- long-running GPU job starves queue
- large uploads
- SSE connection exhaustion
- database lock contention

Mitigations:

- validate scenario count limits
- per-user/project quotas
- global and per-run concurrency limits
- task timeouts
- queue backpressure
- SSE connection limits
- pagination on list endpoints
- health checks and alerting

### 3.6 Elevation of privilege

Threats:

- viewer submits audit
- auditor manages models/users
- project A accesses project B resources
- IDOR via run IDs

Mitigations:

- role-based permissions
- project scoping on all queries
- object-level permission checks
- use scoped querysets/filters
- API contract tests for forbidden roles

### 3.7 Injection

Threats:

- SQL injection
- template XSS
- command injection in worker paths
- YAML/JSON deserialization issues
- prompt injection affecting audit interpretation

Mitigations:

- ORM parameterized queries
- autoescaped templates
- no shell string interpolation for user data
- strict schema validation
- treat model output as untrusted data
- judge prompts should instruct structured output but platform must validate parsed JSON
- prompt injection is a scientific risk; UI should label model-generated content as model output

### 3.8 SSRF

Threats:

- admin registers model endpoint pointing to internal metadata service
- base_url uses `file://`, `gopher://`, private IP ranges
- worker fetches internal resources

Mitigations:

- allow only `http`/`https`
- block localhost/private/link-local ranges unless explicitly enabled for trusted local inference
- maintain optional allowlist for self-hosted endpoints
- validate at registration and before execution
- log blocked attempts

### 3.9 Supply chain

Threats:

- malicious dependency
- unpinned package version
- compromised Docker base image
- simpleaudit checkout altered silently

Mitigations:

- lockfiles
- pinned Docker images
- reproducible build instructions
- record SimpleAudit git commit in manifest
- CI dependency audit
- minimal base images
- regular updates

## 4. Secret handling

Rules:

1. Raw secrets never stored in PostgreSQL.
2. Raw secrets never included in reproducibility manifest.
3. Raw secrets never returned by API.
4. Raw secrets never written to logs.
5. Worker resolves secret reference immediately before client construction.
6. Secret material is cleared from memory where practical.
7. Rotation requires updating secret source, not editing historical runs.

Acceptable secret sources for MVP:

- environment variables injected by Docker Compose
- mounted secret files with restricted permissions

Later:

- vault integration
- encrypted secret table
- per-project secrets

## 5. Prompt and transcript confidentiality

Audit scenarios and transcripts may contain sensitive research, medical, educational, or regulatory content.

Controls:

- project-scoped access
- encrypted TLS in transit
- disk encryption expected in deployment docs
- object storage private
- exports authorized
- logs redact full prompts/transcripts by default
- debug bundles require explicit admin/auditor action

## 6. AI-specific risks

### 6.1 Judge bias/variance

Risk:

- different judges produce materially different verdicts
- users compare incompatible audits
- measured judge effects can dominate target-model effects, so a buried warning is insufficient

Mitigation:

- comparison UI displays judge identity prominently in the comparison header
- standing advisory appears whenever judges differ
- intersection mode is recommended or default for cross-judge comparisons
- manifest records judge identity/profile
- comparison export includes judge compatibility flags
- future judge calibration reports using golden response sets

### 6.2 Model output manipulation

Risk:

- target model produces persuasive unsafe content
- UI renders it as platform guidance

Mitigation:

- visually label model output
- sanitize HTML
- do not execute model-provided instructions
- keep recommendations separate from system text

### 6.3 Data leakage to external models

Risk:

- sending confidential scenarios to external API violates policy

Mitigation:

- model registry marks endpoint as external/local
- UI warns when selecting external endpoint for sensitive project
- later: project-level data residency policies

## 7. Audit logging

Log events:

- user login/logout
- failed login
- role change
- model endpoint create/update/disable
- secret reference change
- scenario publish
- audit submit/cancel/retry
- artifact download
- admin export
- permission denial

Fields:

- timestamp
- actor
- action
- resource type/id
- project
- outcome
- request ID
- IP address where appropriate

## 8. Residual risks

Accepted for MVP if documented:

- single-host Docker Compose has one blast radius
- local inference endpoints may require private-network SSRF allowance
- LLM outputs remain nondeterministic even with frozen inputs
- judge variance remains a scientific limitation

Not accepted:

- raw secrets in DB/logs/manifests
- mutable historical scenario versions
- in-process queue as production path
- SQLite as production database
- unauthenticated multi-user deployment
