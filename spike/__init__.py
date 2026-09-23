"""Phase 4 durable job system spike.

This package validates Hatchet (embedded mode) against the non-negotiable
acceptance criteria in docs/job-system-spike.md BEFORE any real SimpleAudit
model execution is enabled. It uses a fake audit executor and a local SQLite
file to stand in for the PostgreSQL AuditEvent table, so the reliability
properties (persistence across restarts, idempotency, cancellation, retries,
progress durability) can be proven without model calls or a live Postgres.
"""
