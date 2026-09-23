# ADR 006 — Observability: OpenTelemetry + Langfuse or Compatible LLM Backend

Status: proposed  
Date: 2026-09-22  
Deciders: observability/evaluation lead, architecture lead, independent reviewer

## Context

Audits are expensive and scientifically sensitive. Failures must be diagnosable. Users and operators need to understand:

- which scenario failed
- which role call failed: target, auditor, judge
- latency and token usage
- retry behavior
- model/provider errors
- prompt/response characteristics without leaking secrets
- correlation between UI, API, workflow, worker, and LLM calls

The platform should not reinvent LLM observability if a maintained backend such as Langfuse fits.

## Requirements

- trace an audit from submission to completion
- structured logs with correlation IDs
- metrics for queue/workers/LLM calls
- per-scenario execution traces
- token usage by role
- failure diagnosis
- no secrets in telemetry
- self-hostable
- optional in MVP but required for production-grade operations

## Proposed signal model

### Identifiers

Every relevant operation carries:

```text
request_id
user_id
project_id
audit_run_id
workflow_run_id
task_id
scenario_revision_id
trace_id
span_id
```

### Trace shape

```text
audit.submitted
└── audit.run
    ├── audit.prepare
    ├── scenario.execute
    │   ├── target.call
    │   ├── auditor.call
    │   └── judge.call
    ├── audit.aggregate
    └── audit.report
```

For parallel scenarios, each `scenario.execute` is a child span/task under the same audit trace or linked trace with run ID resource attribute.

### Metrics

System:

- `http_request_duration_seconds`
- `queue_depth`
- `worker_active_tasks`
- `worker_queue_wait_seconds`
- `task_duration_seconds`
- `task_retry_total`
- `task_failure_total`
- `sse_active_connections`
- `db_query_duration_seconds`

Audit:

- `audit_scenarios_total`
- `audit_scenarios_completed`
- `audit_scenarios_failed`
- `audit_stage_duration_seconds`
- `llm_call_duration_seconds`
- `llm_tokens_total`
- `llm_error_total`

Labels:

- `role=target|auditor|judge`
- `provider`
- `model_id`
- `status`
- `error_code`
- `worker_pool`

Avoid high-cardinality labels such as raw prompt text, user IDs, or full model names if unstable.

### Logs

Structured JSON with:

- timestamp
- level
- service
- message
- correlation IDs
- error code
- duration
- token counts

Redact:

- API keys
- bearer tokens
- full prompts/transcripts by default
- user PII where identified

Debug mode may enable transcript logging but must warn explicitly.

## Options considered

### Option A: OpenTelemetry + Langfuse

Pros:

- OTel gives traces/metrics/logs correlation
- Langfuse specializes in LLM calls, prompts, evaluations, cost/token tracking
- self-hostable
- avoids building custom LLM observability

Cons:

- two systems to operate
- integration must avoid duplicate/confusing views
- secret redaction must be enforced at SDK/instrumentation layer

### Option B: OpenTelemetry only

Pros:

- one standard
- simpler conceptually

Cons:

- may require custom dashboards for LLM-specific inspection
- less turnkey prompt/response evaluation view

### Option C: Custom event table only

Pros:

- already needed for durable progress

Cons:

- not sufficient for distributed tracing/LLM debugging
- risks becoming ad-hoc observability swamp

## Decision

Use **OpenTelemetry** as the instrumentation standard.

Use **Langfuse or compatible self-hosted LLM observability backend** for LLM-specific traces when enabled.

PostgreSQL `AuditEvent` remains the durable source for user-facing progress and SSE replay. Telemetry is diagnostic, not the authoritative result store.

Integration rules:

1. SimpleAudit role calls are wrapped in spans.
2. Span attributes include role, provider, model ID, token counts, status, error code.
3. Prompt/response content is off by default; opt-in per deployment with confidentiality warning.
4. Secrets are never attributes.
5. Audit run ID is a resource/span attribute.
6. Worker and web share the same OTLP endpoint configuration.

## Consequences

Positive:

- failures become diagnosable
- token/latency visibility improves
- LLM behavior can be inspected without rebuilding tooling
- correlation across components becomes standard

Negative:

- more moving parts
- requires discipline to avoid telemetry leakage
- optional services complicate minimal deployment

## Validation required

- trace contains API → workflow → worker → target/auditor/judge spans
- log line can be joined to trace via `trace_id`
- token metrics match stored result totals within test tolerance
- no API key appears in exported telemetry
- disabling Langfuse does not break audit execution
- SSE progress still works without telemetry backend
