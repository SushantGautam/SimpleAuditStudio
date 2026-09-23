# ADR 001 — Web Framework: Django

Status: proposed  
Date: 2026-09-22  
Deciders: architecture lead, backend lead, independent reviewer

## Context

The platform needs a web/API framework for:

- authentication and authorization
- forms and admin workflows
- REST API
- SSE progress streams
- ORM and migrations
- OpenAPI generation
- server-rendered or hybrid UI
- audit logging
- self-hosted deployment

The current prototype uses FastAPI + SQLite. The production requirement explicitly prefers Django + PostgreSQL unless investigation shows a strong reason otherwise.

## Options considered

### Option A: Django + DRF

Pros:

- mature ORM and migrations
- built-in auth/admin
- strong ecosystem for RBAC, audit logs, file storage
- good fit for transactional domain invariants
- easy to add OpenAPI via DRF Spectacular
- suitable for nontechnical admin UIs

Cons:

- heavier than FastAPI
- SSE requires async view or channel layer/streaming response care
- initial scaffolding larger

### Option B: FastAPI + SQLModel/SQLAlchemy

Pros:

- modern async
- lightweight
- good OpenAPI defaults
- prototype already uses it

Cons:

- less batteries-included auth/admin
- more custom work for RBAC, audit log, migrations discipline
- prototype’s FastAPI usage is tied to POC shortcuts and should not anchor production choice

### Option C: Flask/Lite monolith

Pros:

- simple

Cons:

- too much custom infrastructure for production multi-user needs

## Decision

Use **Django** with Django REST Framework for API endpoints.

Use PostgreSQL as the database. Use Django ORM migrations as the schema source of truth. Add DRF Spectacular or equivalent for OpenAPI.

SSE may be implemented with Django streaming responses initially. If backpressure/multi-instance fan-out becomes problematic, introduce a durable event bridge or Channel Layer without changing the public API.

## Consequences

Positive:

- faster secure baseline
- stronger migration story
- better admin/authorization foundations
- aligns with repository instruction

Negative:

- team must follow Django project structure discipline
- business logic must remain in services, not views
- async/SSE behavior must be tested carefully

## Validation required

- fresh `migrate` from empty DB
- API contract tests
- auth/RBAC tests
- SSE replay test
- load test for concurrent SSE connections
