# ADR 004 — Scenario Versioning: Immutable Revisions and Set Versions

Status: proposed  
Date: 2026-09-22  
Deciders: data/versioning lead, SimpleAudit domain lead, independent reviewer

## Context

Scenarios are scientific inputs. If a scenario changes after an audit used it, historical results must remain interpretable. The current prototype already models scenarios, revisions, sets, and set versions, but production must enforce the invariant with schema constraints and service rules.

Core rule:

**Audits reference immutable `ScenarioSetVersion` rows, never mutable sets.**

## Requirements

- edit scenario without mutating old content
- publish set version as ordered snapshot
- compute deterministic content hash
- allow import/export
- allow diff/history
- prevent deletion of referenced revisions
- support fork/duplicate
- preserve execution order
- make accidental mutation impossible through normal API

## Design

### Entities

```text
Scenario
  stable identity, mutable metadata only

ScenarioRevision
  append-only content snapshot

ScenarioSet
  mutable named collection

ScenarioSetVersion
  append-only published snapshot

ScenarioSetVersionItem
  ordered revision membership in a version
```

### Identity and hashing

`Scenario.key` is stable within project.

`ScenarioRevision.content_hash` is computed over execution-relevant fields:

- description
- expected_behavior canonical JSON
- test_prompt
- metadata fields marked execution-relevant

`ScenarioSetVersion.content_hash` is computed over:

- ordered item positions
- scenario IDs or keys
- revision IDs
- revision content hashes

Canonical JSON rules:

- sorted object keys
- stable list order where semantically meaningful
- UTF-8 encoding
- no timestamps included unless explicitly part of content

### Immutability enforcement

Application rules:

- no update/delete endpoints for `ScenarioRevision`
- no update/delete endpoints for `ScenarioSetVersion`
- no update/delete endpoints for `ScenarioSetVersionItem`
- archive scenarios instead of deleting
- database permissions may deny UPDATE/DELETE on append-only tables for application role

Schema rules:

- unique `(scenario_id, revision)`
- unique `(set_id, version)`
- unique `(version_id, scenario_id)`
- unique `(version_id, position)`
- foreign keys from items to revisions
- audit run FK to `ScenarioSetVersion`

### Publishing workflow

1. user edits scenarios, creating new revisions
2. user selects set membership/order
3. user publishes version
4. system inserts `ScenarioSetVersion`
5. system inserts items referencing exact revisions
6. system computes and stores content hash
7. version becomes selectable for audits

### Audit pinning

When creating an audit:

- require `ScenarioSetVersion.id`
- store ID on `AuditRun`
- manifest includes version number and content hash
- worker loads scenarios only through that version
- retry uses same version

## Comparison implications

Comparison engine can determine:

- same set version
- overlapping scenario revisions
- differing revisions by scenario key
- excluded scenarios in intersection mode

UI must show differences clearly.

## Consequences

Positive:

- historical audits remain scientifically valid
- users can iterate scenarios safely
- diffs/history become possible
- reproducibility manifest is trustworthy

Negative:

- storage grows with revisions
- UI must explain versions to nontechnical users
- import/export must preserve identity and order

## Validation required

- edit after audit does not change v1 hash/content
- publish creates new version number
- delete/archive does not break historical run
- duplicate identical content detected
- import/export round-trip preserves hash
- audit cannot be created against unpublished mutable set
