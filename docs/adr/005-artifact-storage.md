# ADR 005 — Artifact Storage: S3/MinIO Object Storage

Status: proposed  
Date: 2026-09-22  
Deciders: architecture lead, DevOps/release lead, independent reviewer

## Context

Audits produce large outputs:

- full SimpleAudit result JSON
- multi-turn transcripts
- judge rationales
- exported reports
- imported scenario files
- debug bundles

PostgreSQL should store queryable result rows and metadata, but not large blobs inline. The current prototype writes artifacts to local `data/` paths, which is not suitable for multi-worker or durable self-hosted deployment.

## Requirements

- store large immutable artifacts
- support multiple workers writing concurrently
- authorize downloads
- preserve integrity
- support backup/restore
- work in Docker Compose
- optional remote/object storage compatibility
- avoid exposing raw storage publicly

## Options considered

### Option A: MinIO/S3-compatible object storage

Pros:

- standard API
- runs in Docker Compose
- scales to real S3 later
- good for immutable objects
- signed URLs supported
- easy bucket lifecycle policies

Cons:

- another service to operate
- requires backup strategy

### Option B: Local filesystem volume

Pros:

- simple

Cons:

- poor multi-host story
- weaker durability if container ephemeral
- harder authorization/integrity model
- not acceptable as canonical production path

### Option C: PostgreSQL large objects

Pros:

- one system

Cons:

- bloats primary DB
- worse concurrency/backup characteristics
- not ideal for large artifacts

## Decision

Use **S3-compatible object storage**, with **MinIO** as the default self-hosted implementation.

Bucket layout:

```text
projects/{project_id}/
  scenarios/imports/{import_id}/{filename}
  audits/{run_id}/
    results.json
    scenarios/{version_item_id}/transcript.json
    reports/{report_id}.html
    exports/{export_id}.json
    debug/{bundle_id}.tar.gz
```

Object metadata:

- SHA-256
- content type
- size
- run ID
- project ID
- kind

Database stores `AuditArtifact` rows with URI and hash. Objects are immutable after upload.

Access model:

- bucket private
- web/API verifies user permission before issuing short-lived signed URL or streaming through backend
- workers use service credentials scoped to bucket
- browser never gets permanent public URLs

## Integrity

Object keys must be deterministic and collision-safe:

```text
projects/{project_id}/audits/{run_id}/{kind}/{version_item_id_or_run_scope}/{attempt_or_final}/{uuid_or_hash}.ext
```

For final artifacts, prefer a stable content-derived or run-scoped key that can
be safely re-uploaded without changing semantic identity. For attempt-specific
debug artifacts, include attempt number.

At upload:

1. compute SHA-256
2. upload object to deterministic key
3. write `AuditArtifact` row with hash
4. optionally verify by reading metadata/hash back

Crash handling:

- crash between upload and DB write may create orphan objects
- retries must not overwrite a different final artifact
- reconciliation job or lifecycle policy may clean unclaimed objects
- final result rows are authoritative for which artifact URI/hash is valid

At download:

1. authorize
2. stream or sign URL
3. client may verify hash if provided

## Backup

Back up bucket with:

- `mc mirror`
- S3 versioning if enabled
- periodic snapshots

Restore test must verify artifact hash for a historical audit.

## Consequences

Positive:

- scalable artifact storage
- multi-worker safe
- clean separation of queryable results and large payloads
- path to external S3

Negative:

- operational component
- signed URL/security design required
- backup must include both DB and objects

## Validation required

- concurrent uploads do not overwrite
- unauthorized download returns 403
- artifact hash matches downloaded bytes
- restore from backup preserves artifact access
- large transcript does not bloat PostgreSQL
- object URI scheme works for MinIO and external S3
