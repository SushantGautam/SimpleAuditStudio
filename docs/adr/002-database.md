# ADR 002 — Database: PostgreSQL

Status: proposed  
Date: 2026-09-22  
Deciders: architecture lead, data/versioning lead, independent reviewer

## Context

The platform’s core scientific invariant is that historical audits must remain interpretable after scenarios, models, and configurations change. This requires strong relational integrity, transactions, constraints, and durable querying.

Current prototype uses SQLite for zero-setup portability. The production requirement explicitly says not to use SQLite as the production database.

## Requirements

- transactional consistency
- foreign keys
- unique constraints
- check constraints
- JSONB for structured snapshots/metadata
- concurrent reads/writes from web and workers
- reliable migrations
- backup/restore
- row-level or query-level project scoping
- durable event storage for SSE replay
- support for long-running job state

## Options considered

### Option A: PostgreSQL

Pros:

- mature ACID database
- JSONB + relational hybrid
- strong constraints/indexes
- excellent backup ecosystem
- standard for Django
- supports concurrent workers

Cons:

- external service required
- operational burden vs SQLite

### Option B: SQLite

Pros:

- zero setup
- simple prototype

Cons:

- poor multi-process write concurrency
- weaker operational story
- explicitly rejected for production by repository instructions

### Option C: MySQL/MariaDB

Pros:

- familiar
- widely available

Cons:

- less ideal JSONB/document semantics than Postgres
- no strong reason to prefer over Postgres for Django

## Decision

Use **PostgreSQL** as the authoritative database.

Store:

- users/projects/roles
- scenario revisions/versions
- model registry
- audit runs
- result rows
- metrics
- events
- artifacts metadata
- comparisons
- audit logs

Use JSONB for:

- config snapshots
- generation parameters
- judgment structures
- event payloads
- summary metrics

Do not store raw secrets in PostgreSQL.

## Consequences

Positive:

- enforce immutability with constraints and service rules
- durable progress/event replay
- safe multi-worker access
- production-grade backups

Negative:

- Docker Compose must include Postgres
- migrations must be tested
- operators need backup procedure

## Validation required

- migration from empty DB
- upgrade migration test
- constraint violation tests
- concurrent worker write test
- backup/restore reproducibility test
