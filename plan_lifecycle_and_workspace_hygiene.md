# Lifecycle and Workspace Hygiene Plan

## Status

Implementation in progress on `feature/auto_protocol`. The completion ledger is
the accountability source for what has landed in code, tests, docs, deployment,
and real Registry/Telegram proof.

This plan is intentionally separate from `plan_auto_protocol.md` and
`plan_auto_protocol_polish.md`.

Auto Protocol depends on this work because generated protocols produce
artifacts, runtimes, and runs that need durable lifecycle behavior. The scope
here is broader than Auto Protocol: it covers all protocol runs, artifacts,
runtimes, bot workspaces, protocols, skills, agents, Registry APIs, Telegram,
operator cleanup, and documentation.

## Completion Ledger

| Outcome | Backend Contract | Registry UI | Telegram | Docs | Focused Tests | Real Surface Proof |
|---------|------------------|-------------|----------|------|----------------|--------------------|
| Durable artifact snapshot | Implemented | Implemented in artifact rows | Fallback links through artifact routes | Updated | Focused passing | Pending live proof |
| Workspace inventory by run | Implemented via bot management dry run | Dashboard cleanup dry run | N/A | Updated | Focused passing | Pending live proof |
| Run archive/delete | Implemented soft archive/delete/restore | Implemented on run detail and filters | Commands implemented; Registry remains primary confirmation UI | Updated | Focused passing | Pending live proof |
| Protocol lifecycle clarity | Existing archive/delete rules preserved | Existing UI preserved | Existing lifecycle preserved | Updated | Focused passing | Pending live proof |
| Skill lifecycle clarity | Existing lifecycle preserved | Existing UI preserved | Existing Telegram preserved | Updated | Focused passing | Pending live proof |
| Agent disable/archive/delete semantics | Existing soft delete preserved | Existing UI preserved | Existing summaries preserved | Updated | Focused passing | Pending live proof |
| Runtime stop/archive/delete cleanup | Existing runtime lifecycle preserved; archive can stop runtimes first | Implemented controls retained | Existing runtime callbacks preserved | Updated | Focused passing | Pending live proof |
| Manual cleanup with dry run | Implemented | Implemented in Dashboard | N/A | Updated | Focused passing | Pending live proof |
| Automatic workspace garbage collection | Runtime expiry implemented; workspace file deletion intentionally requires confirmed dry run | Status and dry-run eligibility | N/A | Updated | Focused passing | Pending live proof |
| Workspace wipe recovery behavior | Snapshot fallback implemented | Artifact rows expose retained package | Artifact links use same fallback | Updated | Focused passing | Pending live proof |
| Export includes durable artifact manifest | Implemented | N/A | N/A | Updated | Focused passing | Pending live proof |

Every row must be completed against the same Registry and SDK contracts. Do not
create a second artifact browser, Telegram-only cleanup path, or bot-local
cleanup command that bypasses Registry state.

Runtime proof note, 2026-05-07: a live Registry risk-engine run proved artifact
runtime start/stop, routing, runtime events, and snapshot/package availability,
but it also exposed that Registry start still dispatched a process-backed
manifest whose `start_command` used Maven developer mode. That path is now
blocked before bot dispatch using the shared runtime manifest policy, and final
acceptance auto-revises manifest contract defects instead of relying on a manual
operator return. The remaining live proof must use a regenerated or revised
prepared artifact, not a developer-mode start command.

Follow-up proof note, 2026-05-07: real Safari was used against the deployed
Registry run detail for risk-engine run `2d44384b9cce4bebae814e2616fdd934`.
Registry logs showed the Safari runtime-start POST returning `409 Conflict`
before bot dispatch, and the UI stayed on an enabled `Start app` action with the
Maven blocker visible inline. This proves the non-run-ready start is now a
product-visible lifecycle decision; prepared-artifact start/open/stop proof is
still pending.

## Problem Statement

Bot container workspaces can become messy. Protocol runs create source files,
build outputs, dependency caches, package directories, runtime logs, temporary
files, and sometimes long-lived runnable systems. Some of those files are the
actual product outcome. Others are scratch data that should not live forever.

Today, Registry records the run audit trail and artifact metadata in Postgres:
runs, stages, transitions, tasks, artifact keys, paths, sizes, hashes, runtime
instances, and runtime events. For normal workspace file artifacts, however, the
actual bytes are still resolved from the bot workspace or mounted host path. If
that workspace is wiped from the bot side or host side, the Registry can still
show the run history, but artifact open/download/runtime start can fail because
the file path no longer exists.

That is not good enough for a commercial product. Users need to trust that
important outputs remain available, that cleanup does not destroy audit history,
that failed or stuck runs can be cleaned up, and that protocols, skills, and
agents have understandable lifecycle controls.

## Lessons Learned

- Artifact metadata is not the artifact. A verified path and hash are useful
  audit evidence, but they do not preserve the output after the workspace is
  removed.
- Postgres should remain the audit and metadata source of truth. It should not
  become a dumping ground for arbitrary large binaries, build trees, videos,
  Maven repositories, or multi-file app packages.
- Produced artifacts need a durable package store. A run should be able to
  survive bot workspace cleanup while preserving user-facing outputs.
- Cleanup is only safe after declared produced artifacts have been snapshotted
  or explicitly marked as not retained.
- Archive and delete are different product actions. Archive hides and stops
  active work while preserving audit. Delete removes or redacts selected data
  according to strict rules.
- Agent deletion is usually soft deletion. Historical runs must still explain
  which agent acted, even if that agent is no longer available.
- Runtime stop/archive/delete is not the same as artifact delete. Stopping a
  process should not remove the package it was serving.
- A global "wipe demo data" endpoint is not a product lifecycle model. It is an
  operator reset tool and should remain clearly separate.

## Current State

### Already Present

- Protocol drafts can be deleted only when unpublished and unused.
- Published protocols can be archived.
- Agents can be soft-deleted and hidden from normal listings.
- Runtime instances have start, stop, archive, delete status flows.
- Runtime processes have bot-side expiry reaping.
- Registry maintenance can mark expired runtime state.
- Protocol run export includes run metadata, stages, tasks, artifacts, runtime
  instances, runtime events, and transitions.
- Skill storage supports deleting a skill track, and user-facing skill flows
  include lifecycle actions such as submit, approve, publish, archive, install,
  uninstall, and update.
- Registry has a coarse workspace-data cleanup endpoint intended for broad demo
  resets, preserving agents, credentials, skills, guidance, and tokens.

### Gaps

- Produced workspace artifact bytes are not durably snapshotted outside the
  workspace by default.
- Run archive/delete does not exist as a first-class product lifecycle.
- Workspace cleanup is not tied to run retention, artifact durability, or
  operator-visible dry runs.
- Runtime archive/delete records state but does not define package retention
  versus scratch cleanup deeply enough.
- Skill and agent lifecycle semantics are not surfaced consistently for
  non-technical operators.
- A workspace wipe can leave old runs with broken artifact actions.
- The Dashboard does not offer safe cleanup categories, size estimates, dry
  runs, or per-agent/per-run cleanup controls.
- Telegram does not yet provide concise lifecycle links for run archive/delete
  or workspace hygiene actions.

## Product Decisions

1. Use a dedicated plan file.
   This is cross-cutting platform lifecycle work, not an Auto Protocol-only
   feature. Auto Protocol should reference this plan for artifact durability and
   workspace lifecycle expectations.

2. Keep one artifact pipeline.
   Extend the existing Registry artifact metadata, content routes, runtime
   routes, and SDK records. Do not add a second artifact browser, second run
   model, or Telegram-only storage path.

3. Store durable artifact bytes outside Postgres.
   Postgres stores metadata, hashes, manifests, lifecycle state, and pointers.
   The durable store can initially be filesystem-backed under a Registry-owned
   artifact root, with content-addressed package files and manifest records.
   The API must not depend on this being local forever.

4. Snapshot declared produced artifacts.
   When a stage reports a declared output artifact, Registry records the
   metadata and snapshots the file or directory package into durable artifact
   storage when the path is available. Multi-file artifacts are stored as
   packages and remain downloadable as zip.

5. Preserve path-based serving as a live convenience, not as the only source.
   If the workspace path still exists, Registry can serve it. If it does not,
   Registry falls back to the durable snapshot. If neither exists, the UI shows
   a clear unavailable state.

6. Define artifact retention explicitly.
   Each artifact should have retention state: `active`, `archived`,
   `expired`, `deleted`, or `unavailable`. Retention state is separate from the
   stage verification state.

7. Archive before delete.
   Archive hides from default views, stops runtimes, preserves audit, preserves
   retained artifact packages, and marks the record as no longer active. Delete
   is stricter and requires explicit confirmation.

8. Run cleanup must stop runtimes first.
   A run cannot be archived or deleted while a runtime for one of its artifacts
   is running. Product controls should offer "Stop runtimes and archive" as a
   single guided action.

9. Workspace cleanup must be explainable.
   Operators see a dry run before cleanup: what will be removed, what is
   retained, what is unknown, and what artifact links would break if cleanup
   proceeds.

10. Bot workspace wipe is recoverable only for snapshotted outputs.
    If a host or bot workspace is wiped, Octopus should retain audit state and
    durable artifact packages. Non-snapshotted workspace-only files become
    unavailable and are labeled as such.

11. Protocol lifecycle remains immutable.
    Published protocol versions are not deleted in place. Published protocols
    are archived. Drafts with no runs can be discarded.

12. Skills are content lifecycle objects.
    Published skills should be archived/disabled or superseded, not silently
    deleted when runs or protocols reference them. Draft/private/unreferenced
    skill tracks may be deleted with confirmation.

13. Agents are operational identities.
    Agents should support disable, disconnect, and soft delete. Historical run
    records keep agent identity labels and evidence. Hard delete is an
    operator-only data retention action, not normal product behavior.

14. Cleanup is not a substitute for export.
    If users need to share a result, the run artifact package or run export
    should remain available independent of workspace cleanup.

15. No domain-specific cleanup rules.
    Risk engines, games, analytics tools, and future domains use the same
    artifact, runtime, and lifecycle model.

## Target User Experience

### Run Detail

Users can:

- see whether the run is active, archived, deleted, failed, cancelled, or
  completed
- stop active runtimes
- open the primary artifact if available
- download the primary artifact package even after workspace cleanup
- archive the run
- delete the run when policy allows
- improve the run through Auto Protocol without duplicating prior context
- see why an artifact is unavailable if the workspace was wiped

### Dashboard Cleanup

Operators can:

- inspect disk usage by agent, workspace, run, runtime logs, dependency caches,
  scratch directories, durable artifact store, and unknown files
- run cleanup in dry-run mode
- choose cleanup categories
- preserve active runs and retained artifacts
- stop expired runtimes
- clean transient files safely
- archive old runs before deleting workspace files

### Protocols

Users can:

- discard unused drafts
- archive published protocols
- understand that archived protocols preserve versions and historical runs
- see dependent runs before destructive actions

### Skills

Users can:

- archive, disable, uninstall, or delete according to lifecycle state
- see protocols or agents that depend on a skill
- avoid accidental removal of skills required by published protocols

### Agents

Operators can:

- disconnect or disable an agent
- soft-delete stale agent registrations
- see which runs and protocols referenced the agent
- understand that deleting an agent does not delete its historical work

## Data Model Additions

Extend existing records. Do not add parallel replacements.

### Artifact Snapshot Records

Add `agent_registry.protocol_artifact_snapshots`:

- `artifact_snapshot_id`
- `protocol_artifact_id`
- `protocol_run_id`
- `artifact_key`
- `snapshot_kind`: `file`, `directory_zip`, `text`, `external`
- `storage_uri`
- `content_hash`
- `size_bytes`
- `manifest_json`
- `created_at`
- `created_by`
- `retention_state`
- `retention_until`
- `deleted_at`
- `deleted_by`

For v1, `storage_uri` can point to a Registry-owned filesystem root. The API
must treat it as an opaque URI.

### Workspace Inventory Records

Add `agent_registry.workspace_cleanup_inventory`:

- `inventory_id`
- `agent_id`
- `workspace_ref`
- `protocol_run_id`
- `scan_status`
- `file_count`
- `total_bytes`
- `retained_bytes`
- `transient_bytes`
- `unknown_bytes`
- `summary_json`
- `created_at`

This is an observation table, not the source of truth for artifacts.

### Lifecycle Events

Add or extend lifecycle events for:

- `run_archived`
- `run_delete_requested`
- `run_deleted`
- `artifact_snapshotted`
- `artifact_snapshot_deleted`
- `workspace_cleanup_dry_run`
- `workspace_cleanup_executed`
- `agent_disabled`
- `agent_soft_deleted`
- `skill_archived`
- `skill_deleted`

Use existing event/audit infrastructure where possible.

## Backend API Plan

### Artifact Snapshots

Add endpoints under the existing run artifact namespace:

- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot/content`
- `DELETE /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot`

Rules:

- Snapshot uses the same artifact resolution code already used for content.
- Directory artifacts are stored as zip packages.
- Snapshot creation is idempotent by artifact hash.
- Snapshot delete marks retention state first; physical deletion can occur in
  cleanup after retention policy.
- Artifact content routes should prefer live workspace path, then snapshot,
  then rehearsal/control-plane text, then unavailable error.

### Runs

Add lifecycle endpoints:

- `POST /v1/protocol-runs/{run_id}/archive`
- `DELETE /v1/protocol-runs/{run_id}`
- `POST /v1/protocol-runs/{run_id}/restore`

Rules:

- Running runs cannot be deleted.
- Runs with running runtimes cannot be archived or deleted until runtimes stop.
- Archive preserves audit, artifacts, snapshots, transitions, tasks, and
  runtime events.
- Delete requires terminal or archived state, explicit confirmation, and role
  permission.
- Delete should be soft delete by default. Hard purge is a separate admin
  retention operation.
- Archived runs are restorable until they are deleted or physically purged by
  retention policy.

### Workspace Cleanup

Add endpoints:

- `POST /v1/admin/workspaces/cleanup/dry-run`
- `POST /v1/admin/workspaces/cleanup`
- `GET /v1/admin/workspaces/cleanup/jobs/{job_id}`
- `GET /v1/admin/workspaces/usage`

Request fields:

- `agent_id`
- `workspace_ref`
- `protocol_run_id`
- `categories`
- `older_than`
- `include_archived`
- `include_failed`
- `confirm`

Categories:

- runtime logs
- expired runtime processes
- stage scratch directories
- build caches
- dependency caches
- unreferenced run workspaces
- archived run workspaces
- failed/cancelled run workspaces
- unknown files

Rules:

- Dry run is mandatory for UI-initiated cleanup.
- Cleanup refuses to remove the only copy of a verified artifact unless a
  snapshot exists or the user explicitly chooses to delete the artifact.
- Cleanup must not remove active run workspaces.
- Cleanup must not remove credentials, tokens, agents, skills, guidance, or
  Registry database content.

### Protocols

Keep existing endpoints and tighten UI/contracts:

- Delete remains draft-only and no-runs-only.
- Archive remains the normal lifecycle for published protocols.
- Add dependency previews before archive/delete.

### Skills

Use existing content store/lifecycle where possible:

- expose archive/disable/delete consistently in Registry UI
- block deleting published or referenced skills unless policy allows
- show protocol dependencies
- keep uninstall separate from archive/delete

### Agents

Use existing soft delete and add missing product controls:

- disable routing
- disconnect
- soft delete
- include soft-deleted agents in audit views
- prevent assigning new runs to disabled/deleted agents

## Bot Runtime Plan

### Workspace Scan

Add a management request for workspace usage:

- bot receives roots and optional run/workspace filters
- bot returns file counts, sizes, categories, and sample paths
- bot does not delete anything during scan

### Workspace Cleanup

Add a management request for cleanup execution:

- Registry sends the dry-run plan id and exact file categories
- bot validates paths remain inside approved workspace roots
- bot refuses symlink escapes
- bot removes only files listed in the approved cleanup plan
- bot returns removed count, bytes, failures, and warnings

### Runtime Cleanup

Keep bot-side runtime process reaping. Extend it to:

- report expired process cleanup back to Registry when possible
- include runtime log retention metadata
- separate runtime process cleanup from artifact package cleanup

## Registry UI Plan

### Run Detail

Add lifecycle panel:

- status and retention state
- archive run
- delete run
- stop runtimes and archive
- snapshot artifacts
- download retained package
- unavailable artifact explanation

The primary artifact card should show:

- live workspace available
- snapshot available
- package download available
- runtime available/running/stopped
- cleanup risk if no snapshot exists

### Runs List

Add useful filters:

- active
- needs attention
- completed
- archived
- deleted hidden by default
- has retained artifacts
- missing workspace artifacts
- has running runtimes

Default sort remains recent-first.

### Dashboard

Add workspace hygiene:

- usage by agent/workspace/category
- cleanup dry-run results
- cleanup history
- retention warnings
- links to affected runs/artifacts

### Protocols, Skills, Agents

Lifecycle controls should be visible but restrained:

- archive as primary destructive lifecycle
- delete only when allowed
- dependency preview before destructive action
- clear human-readable consequence text

## Telegram Plan

Telegram should not become the main destructive lifecycle UI. It should provide
progressive controls and deep links.

Add or expose:

- run archive link/action when safe
- run delete deep link to Registry confirmation
- runtime stop/status where already supported
- artifact download link that uses snapshot fallback
- "artifact unavailable" explanation when workspace path is missing
- agent/skill/protocol lifecycle status summaries

High-risk cleanup should link to Registry Dashboard, not run entirely inside
Telegram.

## Retention Policy

Default policy:

- active runs: keep workspace files
- completed runs: snapshot declared artifacts, then workspace scratch is
  cleanup-eligible after a retention window
- failed/cancelled runs: keep workspace files briefly for debugging, then make
  cleanup-eligible after snapshot of any produced artifacts
- archived runs: keep snapshots and audit; workspace files are cleanup-eligible
- deleted runs: hide from default views; physical purge only through retention
  admin policy
- runtime logs: keep tail in DB/runtime event metadata, retain full logs for a
  bounded period, then cleanup

Policy must be configurable but the product should ship with safe defaults.

## Workspace Wipe Behavior

If a bot workspace is wiped:

1. Registry audit remains.
2. Artifact metadata remains.
3. Snapshot-backed artifacts remain open/downloadable.
4. Workspace-only artifacts show unavailable state with a direct explanation.
5. Runtime start is blocked if the package is unavailable.
6. Users can re-run or improve the protocol from the run context.
7. Operators can mark stale workspace paths as cleaned to reduce repeated
   warnings.

This behavior should be tested explicitly.

## Documentation Plan

Update:

- `README.md`: short explanation of artifact retention and cleanup.
- `docs/USER_GUIDE.md`: archive/delete, artifact availability, snapshot
  download, workspace wipe behavior.
- `docs/OPERATIONS.md`: cleanup policy, dry runs, retention, safe demo reset.
- `docs/PROTOCOLS.md`: declared artifacts should be snapshotted; runnable
  artifacts remain packages plus runtime.
- `docs/ARCHITECTURE.md`: Registry metadata, durable artifact store, bot
  workspace responsibilities, lifecycle boundaries.
- `docs/TELEGRAM.md`: lifecycle links and limits in Telegram.
- `docs/registry-openapi.json`: regenerate after route changes.

## Test Plan

### Unit and Store Tests

- snapshot creation for file artifact
- snapshot creation for directory artifact as zip
- idempotent snapshot by content hash
- content route fallback from workspace path to snapshot
- unavailable artifact when neither path nor snapshot exists
- run archive blocked with running runtime
- run delete blocked for active run
- run archive preserves export
- protocol draft delete rules unchanged
- published protocol archive rules unchanged
- skill delete/archive dependency rules
- agent soft delete keeps historical run visibility

### Bot Tests

- workspace scan categorizes files safely
- cleanup dry-run does not delete
- cleanup execution deletes only approved files
- symlink escape blocked
- runtime logs and process cleanup stay separate from artifact package cleanup

### Registry UI Tests

- run detail lifecycle buttons appear in correct states
- deleted/archived runs are hidden from default list
- artifact card shows snapshot fallback
- cleanup dashboard dry-run is readable
- narrow Safari layout remains usable

### Telegram Tests

- artifact link uses snapshot fallback
- archive/delete destructive actions are gated or deep-linked
- unavailable artifact state is readable

### Real Surface QA

- complete a run with a multi-file artifact
- snapshot and download the package
- simulate missing workspace path
- verify artifact still opens/downloads from snapshot
- archive the run
- confirm it disappears from default runs list but remains discoverable
- attempt delete with correct and incorrect state
- verify Telegram links still work

## Implementation Sequence

### Phase 1: Contract Audit and Decisions

1. Inventory current artifact paths, runtime routes, run actions, protocol
   lifecycle, skill lifecycle, agent lifecycle, and cleanup endpoint.
2. Confirm durable artifact root location and environment setting.
3. Define retention states and lifecycle permissions.
4. Write the exact API contract and OpenAPI changes.

### Phase 2: Durable Artifact Store

1. Add snapshot records and storage abstraction.
2. Implement file and directory snapshot creation.
3. Add snapshot content retrieval.
4. Add content route fallback from live path to snapshot.
5. Add export metadata for snapshots without embedding large bytes by default.

### Phase 3: Run Lifecycle

1. Add run archive/delete/restore store methods.
2. Add HTTP routes.
3. Enforce terminal/running/runtime constraints.
4. Record lifecycle events.
5. Hide archived/deleted runs from default views while preserving filters.

### Phase 4: Workspace Inventory and Cleanup

1. Add bot management scan request.
2. Add Registry dry-run endpoint and cleanup job record.
3. Add bot cleanup execution request.
4. Enforce approved-path-only deletion.
5. Add cleanup history and event records.

### Phase 5: Protocol, Skill, Agent Lifecycle Polish

1. Tighten existing protocol archive/delete UI.
2. Add skill dependency preview and lifecycle controls where missing.
3. Add agent disable/soft-delete controls and audit visibility.
4. Ensure no lifecycle operation removes historical audit.

### Phase 6: Registry UI

1. Add run lifecycle controls.
2. Add snapshot/unavailable states to artifact rows.
3. Add workspace cleanup dashboard.
4. Add archived/deleted filters.
5. Verify wide and narrow Safari usability.

### Phase 7: Telegram

1. Add lifecycle status summaries.
2. Add safe runtime/artifact links.
3. Deep-link high-risk cleanup/delete actions to Registry.
4. Verify Telegram Web in real Safari.

### Phase 8: Docs and OpenAPI

1. Update user and operator docs.
2. Update architecture docs.
3. Regenerate OpenAPI.
4. Add focused example notes for runnable/multi-file artifacts.

### Phase 9: Tests and Live Proof

1. Run focused unit/store/UI tests.
2. Run the fast full suite tier after the test-tier work is present; before
   that lands, run the focused suites that cover the changed lifecycle path.
3. Deploy from local repo through `/Users/tinker/octopus`.
4. Test Registry in real Safari.
5. Test Telegram in real Safari.
6. Prove workspace wipe fallback with a snapshotted artifact.

## Acceptance Criteria

- Wiping a bot workspace does not break access to snapshotted produced
  artifacts.
- Workspace-only artifacts fail clearly and honestly when missing.
- Runs can be archived and deleted according to explicit lifecycle rules.
- Protocol lifecycle remains immutable and understandable.
- Skills and agents have safe lifecycle controls without corrupting history.
- Cleanup has dry-run, category selection, path safety, and audit records.
- Runtime stop/archive/delete remains separate from artifact package retention.
- Registry and Telegram use the same APIs.
- Docs match behavior.
- Tests cover the lifecycle rules.
- Real Safari proof confirms the product is usable by a human operator.
