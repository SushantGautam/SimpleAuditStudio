# SimpleAudit Package Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install SimpleAudit as a normal Python dependency in Docker and local environments, derive its version from installed package metadata, and preserve an optional commit ref as separate provenance.

**Architecture:** A committed `simpleaudit-dependency.yaml` is the single source of truth for the package source, required version, and optional Git ref. A shared resolver validates installed metadata and extracts optional PEP 610/Git provenance; the platform no longer uses `SIMPLEAUDIT_ENGINE_PATH` or `sys.path` injection. Docker and local setup install the same dependency specification, while AuditRun manifests retain automatically resolved version and optional commit separately.

**Tech Stack:** Python packaging, `importlib.metadata`, PyYAML, Dockerfile, Makefile, Django tests, factory_boy.

**Spec:** Approved package-based SimpleAudit installation and provenance design from the user conversation.

## Global Constraints

- SimpleAudit must be installed as a Python package, not loaded from a special path.
- `simpleaudit_version` comes from installed package metadata and is never manually duplicated.
- `git_commit` is optional provenance and must not be treated as the version.
- Docker and local setup must consume the same dependency specification.
- Existing audit scientific semantics and frozen manifest fields remain intact.
- The web process must remain able to start without importing the engine; the worker validates the dependency before execution.
- Existing tests and all-pages smoke coverage must continue to pass.

---

### Task 1: Add canonical dependency specification and resolver

**Files:**
- Create: `simpleaudit-dependency.yaml`
- Create: `infra/simpleaudit_package.py`
- Modify: `requirements.txt`
- Modify: `config/settings.py`
- Test: `infra/tests/test_simpleaudit_package.py`

**Interfaces:**
- `load_dependency_spec(path=None) -> SimpleAuditDependencySpec`
- `resolve_installed_metadata() -> SimpleAuditMetadata`
- `SimpleAuditMetadata.version: str`
- `SimpleAuditMetadata.commit: str | None`
- `SimpleAuditMetadata.location: str | None`

- [ ] **Step 1: Write failing resolver tests** covering package version discovery, missing package failure, version mismatch, and optional commit extraction.
- [ ] **Step 2: Run the focused tests and verify they fail.**
- [ ] **Step 3: Implement YAML parsing and installed-package metadata resolution using `importlib.metadata.version()` and `direct_url.json` when available.
- [ ] **Step 4: Remove `SIMPLEAUDIT_ENGINE_PATH` from runtime loading and make engine imports use the installed package.
- [ ] **Step 5: Run focused resolver and engine integration tests.

### Task 2: Install the same dependency in Docker and local setup

**Files:**
- Modify: `Dockerfile`
- Modify: `Makefile`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `.env.local.example`
- Test: `infra/tests/test_deployment_config.py`

**Interfaces:**
- Docker build reads `simpleaudit-dependency.yaml` and installs the selected package/ref.
- `make local-setup` installs the selected package/ref before migrations.

- [ ] **Step 1: Add a build/install script shared by Docker and local setup.
- [ ] **Step 2: Make the script install the Git ref when configured, otherwise install the requested package version.
- [ ] **Step 3: Make Docker invoke the script instead of cloning `/opt/simpleaudit`.
- [ ] **Step 4: Make local setup invoke the same script.
- [ ] **Step 5: Remove `SIMPLEAUDIT_ENGINE_PATH`, manual version, and manual commit settings from example configs.
- [ ] **Step 6: Test generated install arguments without making network calls.

### Task 3: Populate and validate audit provenance automatically

**Files:**
- Modify: `infra/worker.py`
- Modify: `audits/services.py`
- Modify: `config/settings.py`
- Test: `infra/tests/test_audit_run_freeze.py`
- Test: `infra/tests/test_engine_integration.py`

**Interfaces:**
- Worker constants are resolved from installed metadata at process startup.
- `create_audit_run()` receives no user-supplied SimpleAudit version/commit for normal operation.
- The frozen manifest records resolved version and nullable optional commit.

- [ ] **Step 1: Add failing tests proving settings provenance is derived from installed metadata.
- [ ] **Step 2: Implement startup metadata resolution and retain separate version/commit values.
- [ ] **Step 3: Preserve mismatch failure when a frozen run does not match the worker package.
- [ ] **Step 4: Run provenance and audit freeze tests.

### Task 4: Update documentation and remove obsolete path guidance

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `Dockerfile`
- Modify: `infra/engine.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Document version-only and optional-ref configuration.
- [ ] **Step 2: Document automatic version discovery and optional commit provenance.
- [ ] **Step 3: Remove `/opt/simpleaudit`, `SIMPLEAUDIT_ENGINE_PATH`, and duplicate manual provenance instructions.
- [ ] **Step 4: Scan the repository for stale references.

### Task 5: Full validation and independent audits

**Files:**
- Test: all project tests and deployment checks

- [ ] **Step 1: Run focused package/provenance tests.
- [ ] **Step 2: Run all Django tests.
- [ ] **Step 3: Build Docker images and run the health checks.
- [ ] **Step 4: Run the all-pages smoke test and deployment smoke checks.
- [ ] **Step 5: Dispatch independent sub-agents to audit packaging/provenance and Docker/local parity.
- [ ] **Step 6: Fix any findings and rerun all validation.
