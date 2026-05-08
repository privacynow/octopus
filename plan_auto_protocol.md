# Auto Protocol Product Plan

## Status

This is the single canonical plan for Auto Protocol, runnable artifacts, review
evidence, artifact lifecycle, Registry/Telegram surfaces, SDK-backed bot
awareness, and shared file/resource ingress.

Do not create additional plan files for these areas. If a new issue affects
Auto Protocol, protocol runs, artifacts, runtimes, Registry, Telegram, future
bot transports, lifecycle, or SDK contracts, update this file in place.

Implementation is in progress on `feature/auto_protocol` and deployed through
the `/Users/tinker/octopus` checkout when proof is recorded below.

Current proven baseline:

- Auto Protocol creates and revises normal protocol drafts through the canonical
  protocol lifecycle.
- Runs can produce multi-file artifacts with package download and artifact
  browsing.
- Runnable artifact manifests are parsed, validated, persisted, and started
  through Registry and bot runtime contracts.
- Registry routes runnable UI/API traffic through stable runtime URLs instead
  of exposing raw bot ports.
- Telegram can use Registry APIs to list artifacts, deliver packages, and start
  or inspect runtimes.
- Runtime manifests using developer/build commands at user start are blocked by
  product policy before bot dispatch.
- Final acceptance can transition back into revise flow when runtime manifest
  defects are product blockers; an operator return is not the acceptance path.
- Registry run detail surfaces primary outcome readiness, declared or inferred
  outcome, release-evidence availability, and runtime/evidence checks.
- Artifact runtime events, logs/status summaries, snapshots, package retention,
  and exports are represented through Registry state.
- Real Safari and Telegram Web proof exists for the prepared Java risk-engine
  runtime `d38dab75b929405a9e4a3f1407491e76`.
- Shared SDK resource records now cover Registry uploads, Auto Protocol
  create/revise, manual run launch, improve-run, conversation messages, direct
  assignments, Telegram upload registration, and bot-side materialization.

Current product watch item:

- Future Slack, WhatsApp, and other bot implementations must use the SDK
  resource records and Registry resource APIs instead of copying
  surface-specific attachment behavior.

## Completion Ledger

This ledger is the acceptance bar. A row is complete only when the behavior is
implemented through shared contracts, covered by focused tests, documented where
user-visible, deployed when relevant, and proved through the human-facing
surface.

| Outcome | Current State | Remaining Bar |
|---------|---------------|---------------|
| Canonical Auto Protocol pipeline | Implemented through normal protocol draft, publish, and run paths | Keep generation, revise, improve-run, and manual edits on one protocol model |
| Primary outcome surfacing | Registry run detail shows readiness summary and primary artifact actions | Keep evidence tied to the declared user outcome, not just files or runtime launch |
| Runnable artifact manifests | Implemented and enforced for runtime artifacts | Continue blocking build/developer commands at user start; no scenario-specific exceptions |
| Registry runtime routing | Implemented for standard HTTP UI/API traffic | Preserve Registry as user-facing router and bot runtime as process executor |
| Telegram runtime path | Implemented through Registry APIs and links | Keep future transports on the same SDK/Registry contracts |
| Review evidence | Runtime acceptance gate and revise transition implemented | Ensure reviewers exercise runtime/UI/API when declared and persist rationale |
| Lifecycle and retention | Runtime lifecycle, artifact package retention, snapshots, and exports implemented | Complete operator cleanup proof and preserve audit after workspace cleanup |
| Runs discovery | Recent human-originated runs surface by default | Keep generated/audit filtering explicit, not the default user path |
| Improve existing run | Registry path implemented through Auto Protocol revise context | Keep it as protocol improvement, not artifact patching or a second generator |
| SDK-backed bot awareness | Registry and Telegram receive shared awareness briefs | Future bot implementations must implement SDK ports, not copy surface code |
| Java/Maven risk-engine proof | Prepared Java artifact run `d38dab75b929405a9e4a3f1407491e76` proved in Safari and Telegram | Keep this as representative proof, not hard-coded product logic |
| Shared file/resource ingress | Implemented through SDK resource contracts, Registry upload/attach UX, protocol/conversation/run resource refs, Telegram upload registration, Registry delivery materialization, deployed Safari proof, and access tests | Keep future transports on the same SDK resource records |

Latest proof notes:

- On 2026-05-07, Registry/Safari proved that a non-run-ready Maven
  developer-mode runtime manifest on run `2d44384b9cce4bebae814e2616fdd934`
  returned `409 Conflict` before bot dispatch and surfaced the blocker inline.
- On 2026-05-07, run `d38dab75b929405a9e4a3f1407491e76` proved a prepared Java
  runtime package through Registry/Safari routed UI/API paths and Telegram Web
  package/runtime actions.
- On 2026-05-07, Registry UI proof confirmed that runtime launch is not treated
  as acceptance by itself; the run detail now separates primary outcome
  readiness from release evidence and runtime checks.
- On 2026-05-08, automated proof covered Registry upload/attach/message
  delivery, direct-assignment resource access for routed task targets, inbound
  attachment resource metadata round-tripping, Auto Protocol resource refs into
  run creation, OpenAPI regeneration, and the Registry/Postgres service suite.
- On 2026-05-08, generic runtime guidance was checked to remove
  risk-engine/Maven-specific example leakage from generated protocols.
- On 2026-05-08, deployed Safari proof on `/Users/tinker/octopus` attached
  `octopus-resource-proof.txt` to Registry conversation
  `9c380a0bb8ae945adca982d6e09d4484`, sent the conversation message, and
  Registry logs showed `POST /v1/resources` `201`, conversation message `200`,
  M1 fetching `/v1/resources/50d963c85f325563972d0389d71e9110` plus
  `/content`, and bot execution using a scoped `registry_conversation_*`
  upload directory.

## Problem Statement

Manual protocol authoring is too demanding for the users we are building for.
A user may understand the business, creative, operational, financial, or
technical outcome they need, but they should not need to understand agentic
workflow design before Octopus becomes useful.

Auto Protocol must be the normal easy path inside Registry and bot surfaces:

1. The user describes the desired outcome in plain language.
2. The user can attach relevant source material, examples, data, assets, zips,
   documents, screenshots, or domain files through a common product path.
3. Octopus analyzes the requirement and designs a focused workflow.
4. Octopus produces a normal protocol draft with work packages, artifact
   contracts, review loops, revision paths, assignments, run inputs, resource
   references, and acceptance evidence.
5. The user can inspect, modify, publish, and run the protocol from Registry or
   a bot surface.
6. The completed run makes the primary user-facing outcome obvious and usable.
7. If the outcome is not good enough, the product has a clear improve path that
   revises the protocol or run context through the same pipeline.

The product value is not prompt forwarding. A generated protocol is useful only
if it decomposes the requirement better than a generic prompt, uses relevant
files and context safely, guides agents through the right subproblems, forces
serious review, records revisions, and produces inspectable evidence.

## Lessons Learned

Profits of Doom runs showed that richer decomposition improves outcomes, but
also exposed shallow review, buried primary artifacts, late-stage quality gaps,
and weak playable-outcome validation. The fix is product quality and workflow
design, not a game-specific player or one-off artifact repair.

Manufacturing analytics runs showed that technically supported protocols can
still produce weak user outcomes when they do not guide data readiness,
chart-first workflows, drilldowns, recommendations, evidence, and progressive
user paths.

The risk-engine runs showed that serious software outcomes need semantic
planning, prepared packages, runtime manifests, APIs, UI paths, smoke evidence,
auditability, and reviewer enforcement. Keyword routing and file existence are
not enough.

Lifecycle work showed that artifact metadata is not artifact durability. Users
need retained packages, honest unavailable states, cleanup dry runs, run
archive/delete semantics, and runtime lifecycle controls that do not destroy
audit evidence.

The file-ingress audit showed that Telegram attachment staging exists but is
not the product architecture. Registry, Telegram, and future bot transports need
one SDK-owned resource contract from upload through runtime materialization.

## Product Principles

1. One canonical protocol path.
   Auto Protocol produces and revises normal protocol documents. There is no
   generated-protocol schema, Registry-only schema, Telegram-only schema, or
   import-only schema.

2. One SDK-owned bot/product pipeline.
   Registry, Telegram, and future Slack/WhatsApp-style implementations use the
   same SDK records, Registry APIs, compiler, validation, publish path, run
   path, resource records, awareness brief, and runtime contracts. Surface
   differences are presentation only.

3. No duplicate implementations or compatibility shims.
   Do not add parallel code paths for the same capability. If a field, request
   shape, or flow is wrong, change the shared contract and update callers.

4. Product code owns behavior.
   Models propose structured analysis and work packages. SDK and Registry code
   validate, normalize, compile, repair, reject invalid topology, enforce
   policy, and emit canonical records.

5. Product reviewers make acceptance decisions.
   Runtime/build/review defects must become product states, revise transitions,
   blockers, or evidence requirements. The system cannot depend on Codex being
   present to manually return work for the user.

6. Non-technical users are the default audience.
   Users should not need JSON, Docker, model prompts, internal stage keys,
   database tables, artifact contracts, or hidden command lore.

7. Primary outcomes are first-class.
   Every generated protocol declares a primary artifact contract unless the
   user explicitly asks for a multi-output deliverable. UI and bot surfaces
   surface the primary outcome before supporting reviews and plans.

8. Runtime launch is not acceptance.
   A runnable artifact is not done because it starts. It must satisfy the user
   outcome, expose useful UI/API behavior where required, and carry review and
   release evidence.

9. Generic beats scenario-specific.
   Games, risk engines, dashboards, documents, analytics tools, and future
   domains use the same protocol, artifact, runtime, resource, and lifecycle
   model.

10. Capability is secured, not removed.
    Runnable artifacts execute inside controlled bot containers with scoped
    workspaces, policy validation, assigned ports, logs, timeouts, and audit.
    Registry routes user access; it does not run generated processes.

## Product Decisions

### Decision 1: Auto Protocol Generates Normal Protocols

Auto Protocol creates and revises canonical protocol drafts. Generated drafts
go through the same editor, validation, publish, run, artifact, review, and
versioning lifecycle as manually authored protocols.

Published versions are immutable. Revising a published protocol creates a
draft revision. Existing runs remain tied to the version they used.

### Decision 2: Semantic Planning Is Required

Model-assisted semantic planning is part of the product path. Deterministic
signals may provide hints and coverage checks, but broad keyword routing must
not be the authority for serious protocol shape.

The planner returns structured analysis: requirement summary, assumptions,
domain risks, work packages, artifact contracts, role needs, review rubrics,
primary artifact, resource needs, and suggested run inputs. SDK policy compiles
that into a canonical protocol draft or blocks with a clear error.

### Decision 3: Shared File Resources Are Product Inputs

Users need a friendly path to provide files to Auto Protocol prompts, manual
protocol design, run launches, improve-run flows, and normal conversations.

The product must add one SDK-owned resource contract:

- Registry upload creates a durable input resource with metadata, hash, size,
  mime type, original name, owner/conversation/run context, retention state, and
  access policy.
- Registry UI lets users attach resources to Auto Protocol create/revise,
  manual protocol design, run launch inputs, improve-run requests, and
  conversations.
- Telegram and future channel adapters normalize native uploads into the same
  SDK resource records.
- Bot runtime materializes authorized resources into scoped workspace paths and
  passes those paths through the shared execution context.
- Zips, images, CSVs, docs, audio, game assets, code bundles, and arbitrary
  domain files use the same resource model. Domain-specific handling belongs in
  protocols and agents, not transport code.
- Resource retention and cleanup follow product lifecycle policy; input files
  are not confused with produced output artifacts.

Telegram's current local attachment staging is implementation input, not the
architecture. It must be rationalized behind the shared SDK resource path
instead of copied into each bot surface.

### Decision 4: Runnable Artifacts Are First-Class

Artifacts meant to be used interactively or through APIs declare
`octopus-runtime.json` at the artifact package root. The manifest is metadata
attached to a normal artifact, not a new protocol format.

For backend artifacts, the manifest declares health, UI entry, API base, docs
or spec paths when present, startup behavior, and human-facing core flows.

Runtime manifests must be run-ready. Developer-mode commands that build or
resolve dependencies at user start are blocked before bot dispatch. The product
should revise the artifact/protocol instead of letting users start broken work.

### Decision 5: Registry Routes, Bots Execute

Registry owns persistence, auth, HTTP APIs, UI, public URLs, lifecycle state,
and proxying. Bot runtimes execute provider work and artifact processes inside
their controlled containers through SDK/management contracts.

Runtime traffic must support normal browser and API behavior: HTML, JS, CSS,
images/assets, JSON APIs, common HTTP methods, request bodies, response
headers, redirects, health checks, and API errors. Unsupported transports such
as WebSockets must fail clearly rather than yielding broken links.

### Decision 6: Multi-File Artifacts Stay Downloadable

Every directory artifact exposes package download. Runtime-enabled artifacts
still expose browse and download. Telegram cards include package links where
reachable. API responses and docs make package download discoverable.

### Decision 7: Review Evidence Is Enforced

If an artifact declares a runtime, final acceptance requires linked runtime
evidence: start attempt, health check, UI or API exercise, at least one core
flow, logs/events, limitations, and reviewer rationale.

Review send-back and acceptance reasons must be visible in Registry, Telegram
where appropriate, and exports. Review history remains part of protocol
transitions and task records; do not add a divergent review-history model.

### Decision 8: Runs Default To Human Recency

The default Runs surface is a user history view. Meaningful user-originated
runs from Registry or Telegram appear newest-updated first. Generated/audit
filtering remains available as explicit triage mode, not default behavior.

### Decision 9: Existing Runs Improve Through Auto Protocol

Users can take an existing run, describe what should improve, and generate a
revised protocol from that run context. This is not an artifact patcher, a new
generator, or a side channel.

Run context includes the objective, status, primary artifact, artifacts,
review/evidence state, attached resources, and the user's improvement request.

### Decision 10: Lifecycle Preserves Audit And Artifacts

Produced artifact bytes need durable package storage outside Postgres. Postgres
stores metadata, hashes, lifecycle state, manifests, runtime instances, runtime
events, and pointers.

If the workspace path still exists, Registry can serve it. If it is gone,
Registry falls back to durable snapshots. If neither exists, the UI shows an
honest unavailable state.

Archive hides from default views, stops active runtimes, preserves audit, and
preserves retained artifact packages. Delete is stricter and requires explicit
confirmation. Runtime stop/archive/delete is separate from artifact package
retention.

Workspace cleanup must be explainable through dry runs: what will be removed,
what is retained, what is unknown, and what links would break.

### Decision 11: SDK Awareness Is Shared

Agents receive SDK-backed awareness of protocols, recent runs, stage status,
primary artifacts, runnable outcomes, attached resources, workspace mounts,
active skills, installed tools, and mediated actions.

The awareness contract lives in SDK records and renderers. Registry remains the
authority for persisted state. Bot runtimes consume SDK awareness in normal
execution context. Telegram commands are shortcuts, not the architecture.

## Target User Experience

### Registry

- Auto Protocol create/revise accepts plain-language requirements, constraints,
  and attached resources.
- Manual protocol design can use attached examples, data, assets, or zipped
  source material.
- Run launch exposes protocol inputs and lets the user attach or choose
  resources without writing local paths.
- Improve-run shows the existing run context, primary outcome readiness,
  evidence gaps, and resource attachments, then creates a revised protocol
  through the normal Auto Protocol path.
- Run detail shows primary outcome, readiness, runtime actions, evidence,
  artifact browsing, package download, lifecycle controls, and honest blockers.

### Telegram And Future Bot Surfaces

- Native uploads become the same SDK resources Registry uses.
- Users can ask what protocols/runs/artifacts/resources exist without memorizing
  command syntax.
- Runtime cards privilege the safest next action: start before runtime exists,
  open/status/stop after it starts, and package download when relevant.
- Public links use the configured Registry public URL. Localhost links are
  labeled as host-local and not presented as remotely usable.

### Runtime And Artifact Use

- Start app.
- Open app.
- Open API docs when present.
- Check health.
- Exercise a core UI/API flow.
- View bounded logs/events/status.
- Stop runtime.
- Archive or delete runtime according to permissions.
- Browse files.
- Download package.
- Improve the run when quality or evidence is insufficient.

## Architecture

### Existing Path To Extend

- Registry stores protocols, runs, stages, tasks, artifacts, transitions,
  runtime instances, runtime events, sessions, conversations, and UI/API state.
- SDK owns typed records, protocol models, launch models, transport contracts,
  runtime policy, and client interfaces.
- Bot runtime executes provider/model work, materializes allowed inputs, runs
  generated artifacts, captures logs, and reports state through management
  contracts.
- Telegram is a channel adapter over the shared product APIs and SDK records.

### SDK Contracts

The shared contracts must cover:

- Auto Protocol sessions and design jobs.
- Canonical protocol drafts, published versions, launch inputs, and run
  records.
- Resource records for uploaded or channel-provided input files.
- Inbound messages and attachments normalized to resources.
- Artifact records, artifact package metadata, runtime manifests, runtime
  instances, runtime events, and lifecycle state.
- Awareness records for protocols, runs, artifacts, resources, capabilities,
  actions, and workspace/tool context.
- Review evidence references and acceptance/revise decisions.

### Resource Materialization

Resources are durable Registry records until a run or conversation needs them.
At execution time, the bot runtime receives authorized resource references,
downloads or stages them into an allowed workspace root, and exposes stable
local paths to the agent context.

Agents may inspect, copy, extract, or transform those files according to the
protocol and workspace policy. Generated artifacts may include derived copies
only when the protocol declares them as produced outputs.

### Storage Boundaries

- Input resources are user-provided context.
- Produced artifacts are run outputs.
- Runtime logs/events are execution evidence.
- Workspace scratch is disposable.
- Durable packages preserve important outputs after cleanup.

These categories share lifecycle policy but must not be collapsed into one
ambiguous file bucket.

## Detailed Work Inventory

This section preserves the actionable work from the earlier split plans. The
wording is consolidated, but these items remain part of the plan unless the
ledger marks them implemented and verified.

### Auto Protocol SDK Records

Use explicit records across major boundaries. Do not pass untyped dictionaries
between Registry, SDK, bot runtime, Telegram, or future transports.

Required Auto Protocol records:

- `ProtocolAutoDesignRequestRecord`
- `ProtocolAutoDesignSessionRecord`
- `ProtocolAutoDesignAnalysisRecord`
- `ProtocolAutoDesignModelRequestRecord`
- `ProtocolAutoDesignModelResponseRecord`
- `ProtocolAutoDesignWorkPackageRecord`
- `ProtocolAutoDesignArtifactPlanRecord`
- `ProtocolAutoDesignPrimaryArtifactRecord`
- `ProtocolAutoDesignRolePlanRecord`
- `ProtocolAutoDesignStagePlanRecord`
- `ProtocolAutoDesignReviewPolicyRecord`
- `ProtocolAutoDesignRunProfileRecord`
- `ProtocolAutoDesignWarningRecord`
- `ProtocolAutoDesignEventSummaryRecord`
- `ProtocolAutoDesignChangeSummaryRecord`

Required Auto Protocol request fields:

- `mode`: `create` or `revise`
- `surface`: `registry`, `telegram`, or `api`
- `requirement_text`
- `constraints_text`
- `target_protocol_id`
- `target_version_id`
- `target_draft_revision`
- `source_document`
- `available_agents`
- `available_skills`
- `workspace_ref`
- `actor_ref`
- `chat_ref`
- `resource_refs`
- `idempotency_key`

Required model response fields:

- normalized requirement summary
- domain and risk assessment
- assumptions
- open questions that block generation
- work packages with stable keys and rationale
- roles and required skills
- artifact contracts
- primary artifact contract
- review rubrics
- stage topology hints
- run input recommendations
- acceptance criteria
- evidence requirements
- resource requirements
- warnings

The model response is structured input to the SDK compiler. It is not a
protocol document and it is not accepted directly.

### Resource Records

Add SDK and Registry records for user-provided input resources. The exact table
names may follow existing Registry conventions, but the product needs these
fields:

- `resource_id`
- owner or actor reference
- source surface and source message/conversation/run/session reference
- original filename
- content type and detected mime type
- size in bytes
- content hash
- storage URI
- retention state
- created/updated/deleted timestamps
- metadata JSON
- security scan or validation summary when available

Attachment references must be attachable to:

- Auto Protocol create sessions
- Auto Protocol revise sessions
- manual protocol design
- protocol run launch inputs
- improve-run requests
- Registry conversations
- Telegram conversations
- future bot transport conversations

### Runtime Records

Runtime metadata stays under the existing protocol/artifact SDK area:

- `ProtocolArtifactRuntimeManifestRecord`
- `ProtocolArtifactRuntimeEndpointRecord`
- `ProtocolArtifactRuntimeCommandRecord`
- `ProtocolArtifactRuntimeInstanceRecord`
- `ProtocolArtifactRuntimeEventRecord`
- `ProtocolArtifactRuntimeHealthRecord`
- `ProtocolArtifactRuntimeActionRequestRecord`
- `ProtocolArtifactRuntimeActionResultRecord`

Manifest fields include:

- `runtime_kind`: `static`, `node`, `python`, `java`, `binary`, or `process`
- `working_directory`
- `start_command`
- `environment`
- `internal_port`
- `health_path`
- `ui_path`
- `api_base_path`
- `api_docs_path`
- `openapi_path`
- `readiness_timeout_seconds`
- `idle_timeout_seconds`
- `max_runtime_seconds`
- `resource_limits`
- `required_files`
- `package_entry_label`
- `description`
- `transport_requirements`

Do not add UI-only synthetic runtime fields. If the UI needs runtime state,
persist it.

### Runtime Persistence

Persist runtime instances and events. Minimum instance fields:

- `runtime_instance_id`
- `protocol_run_id`
- `artifact_key`
- `workspace_ref`
- `artifact_content_hash`
- `status`
- `manifest_json`
- `public_base_path`
- `ui_url_path`
- `api_base_path`
- `health_url_path`
- `bot_id`
- `agent_id`
- `process_ref`
- `started_at`
- `updated_at`
- `stopped_at`
- `archived_at`
- `deleted_at`
- `last_health_json`
- `metadata_json`

Minimum event fields:

- `runtime_event_id`
- `runtime_instance_id`
- `protocol_run_id`
- `artifact_key`
- `event_kind`
- `actor_ref`
- `message`
- `payload_json`
- `created_at`

### Artifact Snapshot Records

Produced workspace artifacts need durable snapshots outside Postgres. Minimum
snapshot fields:

- `artifact_snapshot_id`
- `protocol_artifact_id`
- `protocol_run_id`
- `artifact_key`
- `snapshot_kind`: `file`, `directory_zip`, `text`, or `external`
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

For v1, `storage_uri` can point at a Registry-owned filesystem root. API code
must treat it as opaque so the durable store can move later.

### Workspace Inventory And Lifecycle Events

Workspace cleanup needs inventory records, not ad hoc filesystem deletion.
Minimum inventory fields:

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

Lifecycle events must cover:

- `run_archived`
- `run_delete_requested`
- `run_deleted`
- `artifact_snapshotted`
- `artifact_snapshot_deleted`
- `resource_uploaded`
- `resource_attached`
- `resource_detached`
- `resource_deleted`
- `workspace_cleanup_dry_run`
- `workspace_cleanup_executed`
- `agent_disabled`
- `agent_soft_deleted`
- `skill_archived`
- `skill_deleted`

Use existing event and audit infrastructure where possible.

### Requirement Analysis

The semantic planner infers work from the user's requirement and attached
resources, not from a closed keyword table.

For a game requirement, it may infer game design, art direction, animation,
sound, playable implementation, playtesting, release evidence, and attached
asset/mechanics integration.

For manufacturing analytics, it may infer data readiness, synthetic data,
quality checks, dashboard design, analytics dimensions, drilldowns,
recommendations, usability review, browser implementation, and evidence.

For a risk decision engine, it may infer streaming architecture, Java service
structure, DSL grammar, rule execution, feature lifecycle, model catalog
governance, risk-domain scenarios, audit/explainability, UI authoring,
performance testing, and operational controls.

These examples are acceptance probes, not product branches.

### Work Package Policy

Every work package has:

- stable `package_key`
- human display name
- rationale
- owned role
- required skills
- artifact key and artifact description
- resource needs
- dependencies on prior artifacts and resources
- quality bar
- review role
- review rubric
- allowed revise target

Required rules:

- Include requirements/planning work.
- Include exactly one primary outcome package unless the user explicitly
  requests multiple primary deliverables.
- Include final adversarial outcome acceptance that inspects or exercises the
  primary artifact and records release evidence.
- Review or acceptance gates are required for material artifacts.
- Core outcome and acceptance packages cannot be removed by shaping or revision.
- If a reshape would remove the primary outcome, verification, or acceptance
  path, SDK policy blocks it.
- Consolidate related subproblems when a separate package would create shallow
  stages or duplicate reviews.
- Include stage-count rationale when the planner proposes more than the
  standard budget.

### Stage Topology

Generated workflows should be easy to inspect:

1. Requirements/planning work.
2. Requirements review.
3. Domain, architecture, data, UX, content, asset, risk, or other inferred work
   packages, each with review when they produce material artifacts.
4. Primary outcome generation or integration.
5. Final adversarial outcome acceptance.

Stage budgets:

- Small focused outcome: 5 to 7 stages.
- Standard serious outcome: 8 to 12 stages.
- Complex commercial outcome: 13 to 16 stages.
- Hard cap: 18 stages, including review and acceptance stages.

Plans above the cap are invalid. The compiler must consolidate adjacent
packages, scope to a coherent first delivery tranche, or block with a clear
narrowing request.

The primary outcome stage should normally be second-last. The last stage
reviews or exercises that outcome, sends it back with concrete feedback when
needed, and records final release evidence when accepted.

### Review Policy

Reviewers must:

- inspect artifacts directly
- compare against the original requirement
- compare against accepted upstream artifacts
- consider attached resources and whether they were used correctly
- check evidence
- identify missing depth, polish, tests, and weak assumptions
- revise when material doubt remains
- provide concrete revision instructions

Each review domain gets a distinct participant key. Repeated attempts of the
same stage reuse that stage participant for continuity. Server-side review loop
limits are authoritative and cannot be bypassed by UI, Telegram, or API
callers.

### Primary Artifact Policy

Generated protocols declare:

- `primary_artifact_key`
- display name
- producing stage
- artifact kind
- expected path
- open, preview, browse, and download behavior
- evidence requirements
- supporting artifact keys

Run detail uses this metadata for a primary outcome panel with status, actions,
production time, verification state, release evidence, runtime readiness, and
blockers. Supporting artifacts are grouped by purpose: planning, domain/data/UX
or content, implementation support, reviews, release evidence, and resources.

### Session Events And Status UX

Product surfaces need safe status events instead of raw bot logs.

Auto Protocol events include:

- session created
- design job queued
- design job running
- resource attached or removed
- model analysis received
- compiled
- blocked
- revised
- applied
- published
- run started
- run linked

Event summaries include target protocol, source protocol, run id, current
status, warnings, blockers, unresolved assignment count, stage count, package
count, primary artifact key, attached resource count, change summary, actor,
and timestamp.

Run status shows current stage, completed count, active review loop, last
decision, last failure, blocked reason, artifact progress, primary artifact
availability, runtime state, and release evidence.

### Registry APIs

Auto Protocol APIs:

- create session
- revise session
- attach and detach resource
- get session
- list events
- apply draft to editor
- publish
- run
- link run back to session

Runtime APIs:

- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/start`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/stop`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/archive`
- `DELETE /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/events`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/logs`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/health`

Runtime routed access:

- `/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/app/...`
- `/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/api/...`

Resource APIs:

- upload resource
- list resources by owner/context
- get metadata
- download content when authorized
- attach resource to session/run/conversation
- detach resource
- archive or delete resource

Artifact snapshot APIs:

- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot/content`
- `DELETE /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot`

Run lifecycle APIs:

- `POST /v1/protocol-runs/{run_id}/archive`
- `DELETE /v1/protocol-runs/{run_id}`
- `POST /v1/protocol-runs/{run_id}/restore`

Workspace cleanup APIs:

- `POST /v1/admin/workspaces/cleanup/dry-run`
- `POST /v1/admin/workspaces/cleanup`
- `GET /v1/admin/workspaces/cleanup/jobs/{job_id}`
- `GET /v1/admin/workspaces/usage`

Blocked/error responses include stable error code, human message, validation
summary, blocker list, warning codes, and explicit next-step guidance.

### Registry UI Surfaces

Protocols workspace:

- Auto Protocol create/revise form with attachment controls.
- Clear draft preview with outcome summary, work packages, rationale, stage map,
  review loops, roles, primary artifact, supporting artifacts, resource usage,
  warnings, and blockers.
- Normal apply/publish/run flow after gates pass.

Run launch:

- Protocol inputs rendered by type.
- Resource attachment and existing-resource selection.
- Validation before launch when required resources are missing.

Run detail:

- Primary outcome card at top.
- Start/open/API docs/health/logs/stop/archive/delete actions by runtime state.
- Browse and download package remain available.
- Release evidence and review rationale are visible.
- Improve-run action uses the run context and attached resources.
- Runtime, resource, artifact, and lifecycle blockers are clear.

Artifact browser:

- File preview for supported files.
- Directory browse for multi-file packages.
- Download zip/package.
- Runtime manifest visibility for runnable artifacts.
- Snapshot/fallback/unavailable state.

Dashboard cleanup:

- Dry-run first.
- Category selection.
- Size estimates.
- Retained/transient/unknown classification.
- Clear warning when artifact access would break.

### Telegram And Future Bot Surfaces

Telegram supports natural conversation and command shortcuts over the same
Registry APIs:

- create or revise protocol
- attach native uploads as SDK resources
- list protocols and runs
- show primary artifact and package links
- start/open/status/stop runtime through Registry
- improve a selected run
- report blockers and acceptance/revise reasons

Future Slack, WhatsApp, or other bots implement the same SDK ports. Transport
capabilities such as max file size or supported media are exposed as capability
metadata, not new product logic.

### Bot Runtime Responsibilities

The bot runtime:

- executes provider/model work
- downloads or stages authorized resources into allowed roots
- injects SDK awareness and resource paths into execution context
- observes produced artifacts
- validates runtime manifests
- starts supervised runtime processes inside the bot container
- assigns ports through policy
- captures logs
- reports health/events/state to Registry
- stops process groups cleanly
- scans workspace usage for cleanup dry runs

The bot runtime must not invent user-facing Registry links, artifact models, or
Telegram-only state.

### Runtime Start, Stop, And Delete Flow

Runtime start:

1. Registry validates permission and artifact visibility.
2. Registry resolves artifact path, durable snapshot, and manifest.
3. Registry validates run-ready policy before bot dispatch.
4. Registry records `starting`.
5. Registry sends a typed runtime start request through bot management.
6. Bot validates local workspace, policy, required files, resources, and
   transport support.
7. Bot starts a supervised process group.
8. Bot reports process reference, internal port, log path, and health.
9. Registry records state and exposes routed URLs.

Runtime stop:

1. Registry validates permission.
2. Registry sends a typed stop request.
3. Bot terminates the process group.
4. Registry records stopped state and event evidence.

Runtime delete:

1. Stop if running.
2. Remove runtime process metadata and ephemeral runtime files according to
   policy.
3. Preserve protocol artifacts and audit unless delete policy explicitly
   includes them.

### Lifecycle Rules

- Snapshot uses the same artifact resolution code as content serving.
- Directory artifacts snapshot as zip packages.
- Snapshot creation is idempotent by artifact hash.
- Artifact content routes prefer live workspace path, then snapshot, then
  rehearsal/control-plane text, then unavailable error.
- Running runs cannot be deleted.
- Runs with running runtimes cannot be archived or deleted until runtimes stop.
- Archive preserves audit, artifacts, snapshots, transitions, tasks, and
  runtime events.
- Delete requires terminal or archived state, explicit confirmation, and role
  permission.
- Delete is soft by default. Hard purge is an admin retention operation.
- Draft protocols can be deleted only when unpublished and unused.
- Published protocols are archived, not deleted in place.
- Published or referenced skills are archived/disabled/superseded, not silently
  deleted.
- Agents support disable, disconnect, and soft delete while preserving audit.
- Cleanup refuses to remove the only copy of a verified artifact unless a
  snapshot exists or the user explicitly chooses artifact deletion.
- Cleanup must not remove active run workspaces, credentials, tokens, agents,
  skills, guidance, or Registry database content.

### Public URL Configuration

Use one source of truth for Registry and Telegram links:

- Registry bind host.
- Registry bind port.
- Public Registry base URL.
- Runtime public base URL when different.
- Telegram link base URL.
- Local-only mode flag.

Docs explain localhost-only, LAN/private network, public tunnel/reverse proxy,
and server deployments, including security tradeoffs for binding to all
interfaces.

## Implementation Sequence

### Phase 0: Preserve The Canonical Plan

- Maintain this file as the single plan.
- Keep obsolete split plan files deleted.
- Keep status and ledger updates factual and tied to product proof.
- Do not create new plan files for adjacent work in this product area.

### Phase 1: Contract And Records

- Keep Auto Protocol request/response/session records explicit.
- Add resource records and attachment references.
- Keep runtime records under protocol/artifact SDK namespaces.
- Keep artifact snapshot and lifecycle records in Registry state.
- Add serialization tests and contract fixtures.

### Phase 2: Semantic Planner And Compiler

- Include attached resource summaries in planning input.
- Preserve create/revise as one pipeline.
- Enforce requirement analysis, work package rules, stage topology, review
  policy, primary artifact metadata, and evidence requirements.
- Block invalid topology, missing primary outcome, missing acceptance path,
  excessive stages, and unsafe reshape operations.

### Phase 3: SDK File Resource Contract

- Add shared resource models, metadata, access policy, retention state, and
  materialization interfaces.
- Rationalize Telegram attachment staging behind the shared SDK contract.
- Ensure Registry delivery/conversation paths can carry resources instead of
  empty attachment tuples.
- Add focused tests for model serialization, materialization policy, and
  transport normalization.

### Phase 4: Registry Resource APIs And UI

- Add upload/list/select/attach/remove resource APIs.
- Add user-friendly attach controls to Auto Protocol create/revise, manual
  protocol design, run launch, improve-run, and conversations.
- Show attached resources in session/run/conversation context.
- Prevent uploads from becoming artifact outputs unless a run explicitly
  produces them.

### Phase 5: Channel Adapter Parity

- Keep Telegram native uploads working through the same resource path.
- Make future bot implementations depend on SDK resource interfaces, not
  Telegram-specific helpers.
- Ensure channel limitations are surfaced as capability metadata, not new
  product branches.

### Phase 6: Auto Protocol Uses Resources

- Include resource summaries in semantic planning context.
- Let generated protocols request, validate, and consume attached resources as
  run inputs.
- Ensure improve-run can use new files to improve existing outcomes, such as
  updated game mechanics, sound assets, datasets, docs, or code bundles.

### Phase 7: Runtime Manifest And Routing Hardening

- Preserve prepared-artifact runtime policy.
- Keep `octopus-runtime.json` as the runnable artifact manifest.
- Validate command policy before bot dispatch.
- Keep Registry as the user-facing router and bot runtime as executor.
- Maintain standard HTTP UI/API routing for static assets, APIs, redirects,
  request bodies, response headers, health checks, and API errors.
- Block unsupported transports clearly.

### Phase 8: Review Evidence Enforcement

- Ensure final reviewers exercise runtime/UI/API when declared.
- Persist start, health, smoke, logs/events, limitations, and rationale.
- Block acceptance or revise when evidence is missing.
- Surface send-back and acceptance reasons in Registry, Telegram where useful,
  and exports.

### Phase 9: Lifecycle, Retention, And Cleanup

- Preserve package browse/download for every multi-file artifact.
- Snapshot produced artifacts into durable storage.
- Add run archive/delete/restore semantics.
- Add workspace inventory and cleanup dry runs.
- Keep archive/delete behavior separate for runs, runtimes, input resources,
  output artifacts, agents, skills, and protocols.
- Prove workspace-wipe recovery for snapshotted artifacts and honest failure
  for workspace-only files.

### Phase 10: Registry And Telegram UX Closure

- Keep run detail focused on primary outcome readiness.
- Keep runtime controls stateful and clear.
- Keep attached resources visible and manageable.
- Keep Telegram cards concise and action-oriented.
- Make localhost/public-link behavior explicit.
- Verify narrow/mobile UI does not hide primary actions.

### Phase 11: Tests, Docs, Deployment, Proof

- Add focused tests for every regression touched.
- Maintain fast local test targets and a full-suite wall-time budget.
- Add OpenAPI checks for route/doc drift.
- Document actual behavior for Auto Protocol, resources, runtime artifacts,
  review evidence, lifecycle, cleanup, public links, and representative probes.
- Use logs to verify progress instead of arbitrary sleeps.
- Use real Safari for release-critical Registry UI proof.
- Verify Telegram Web or equivalent real bot surface for channel behavior.
- Deploy to `/Users/tinker/octopus` after commit/push when implementation work
  is complete.

## Testing Plan

Required test coverage:

- SDK record serialization and validation.
- Auto Protocol create/revise compiler behavior.
- Requirement analysis and stage topology policy.
- Primary artifact metadata and surfacing.
- Review loop caps and acceptance/revise enforcement.
- Resource upload, metadata, attach/detach, delete/archive, and materialization.
- Telegram attachment normalization into shared resources.
- Registry conversation attachments.
- Manual run launch resource inputs.
- Improve-run resource context.
- Runtime manifest parsing and run-ready command policy.
- Runtime start/stop/health/logs/events through management contracts.
- Registry runtime proxy routing for HTML, JS, CSS, images, JSON, methods,
  bodies, redirects, response headers, health, and API errors.
- Unsupported transport blocking.
- Artifact browse, preview, package download, snapshot fallback, and
  unavailable states.
- Run archive/delete/restore and runtime stop-before-archive/delete.
- Workspace cleanup dry run and path safety.
- Protocol, skill, and agent lifecycle controls.
- Registry UI contract tests for visible actions and wording.
- Telegram command/card tests.
- OpenAPI contract drift checks.
- Real Safari proof for release-critical Registry UI behavior.

Test tiers:

- Unit and policy tests for SDK/compiler/storage behavior.
- Registry API tests for sessions, resources, artifacts, runtimes, lifecycle,
  cleanup, and exports.
- Bot runtime tests with fake supervisors for fast paths.
- Minimal real HTTP runtime tests for representative routing.
- UI contract tests for Registry components.
- Telegram integration tests where bot surface behavior is user-facing.
- Live proof only for release-critical flows, not as a substitute for focused
  automated tests.

## Documentation Plan

Docs must explain actual behavior for:

- Auto Protocol create/revise/improve.
- Manual protocol design and run launch.
- Shared file/resource upload and channel attachment behavior.
- Resource retention, archive, delete, and materialization.
- Primary artifacts, supporting artifacts, browse, preview, and package
  download.
- Runnable artifact manifests and run-ready command policy.
- Registry runtime routing and public URL configuration.
- Telegram runtime/resource behavior and localhost limitations.
- Review evidence, send-back, acceptance, and exports.
- Run, runtime, artifact, resource, protocol, skill, and agent lifecycle.
- Workspace cleanup dry runs and recovery limits.
- Test tiers and representative probes.

## Acceptance Criteria

The plan is complete only when all of the following are true in committed code,
focused tests, docs, deployment where applicable, and real-surface QA:

1. Auto Protocol create/revise/improve uses one canonical protocol pipeline.
2. Registry, Telegram, and future bot surfaces use SDK contracts rather than
   copied surface-specific implementations.
3. Users can upload or attach files through Registry for Auto Protocol,
   manual protocol design, run launch, improve-run, and conversations.
4. Telegram native uploads and future channel uploads normalize into the same
   resource records.
5. Input resources are durably stored, permissioned, listed, attached,
   removed, retained, archived, deleted, and materialized through one model.
6. Bot runtime materializes authorized resources into scoped workspaces and
   exposes them through shared execution context.
7. Resource handling is generic across zips, images, docs, datasets, source
   bundles, sound, game assets, analytics inputs, and domain files.
8. Multi-file produced artifacts always expose browse and zip download.
9. Runnable artifacts declare run-ready runtime manifests.
10. Registry validates and persists runtime state.
11. Bot runtime starts/stops artifact processes through SDK/management
    contracts.
12. Registry routes UI/API access through stable authenticated URLs.
13. Telegram links use configured public base URLs and label localhost links as
    host-local.
14. Runs UI makes runnable primary artifacts obvious and usable.
15. Runs UI defaults to recent meaningful user runs.
16. Users can improve an existing run through canonical Auto Protocol revise,
    apply, publish, and run lifecycle.
17. Users can start, open, check health, inspect logs/events, stop, archive, and
    delete runtime instances according to permissions.
18. Runtime launch alone is never treated as acceptance.
19. Final reviewers exercise runnable artifacts and persist rationale/evidence.
20. Acceptance is blocked or revised for runnable artifacts without linked
    start, health, and smoke evidence.
21. Review send-back and acceptance reasons are visible in Registry, Telegram
    where useful, and exports.
22. Wiping bot workspaces does not break access to snapshotted produced
    artifacts.
23. Workspace-only files fail clearly when missing.
24. Cleanup has dry-run, category selection, path safety, and audit records.
25. Protocol, skill, agent, run, runtime, resource, and artifact lifecycle
    controls preserve history and avoid corrupting references.
26. Tests cover SDK, Registry, bot runtime, Telegram, UI, routing, lifecycle,
    cleanup, review evidence, resource ingress, and Auto Protocol
    planner/validation behavior.
27. Documentation describes actual behavior, not desired behavior.
28. The Java/Maven risk-engine class of backend plus browser UI remains a
    representative proof for generic runtime-artifact capability.
29. Profits of Doom remains a representative proof for generic playable
    artifact quality, primary outcome clarity, and resource-driven improvement,
    without adding a game-specific product path.
30. The deployed `/Users/tinker/octopus` checkout is on the committed branch,
    healthy, and verified in real Safari before claiming release completion.

## Non-Goals

- Additional plan files for this product area.
- A second protocol model.
- A second artifact browser.
- Telegram-only resource or runtime behavior.
- Registry-only prompt strings that bypass SDK awareness.
- Raw Docker port instructions as the primary user experience.
- Hard-coded behavior for games, risk engines, manufacturing, fintech, or any
  single example.
- Building a game player, video-game automation layer, or complex UI exerciser
  inside the product.
- Treating runtime launch as release evidence by itself.
- Hiding package files because a runtime exists.
- Deleting audit evidence as part of normal stop/archive actions.
- Static-only runtime scope that cannot run real backend systems.
- Running generated artifact processes inside Registry.

## Representative Probes

### Profits Of Doom

Use the game runs to prove that Auto Protocol can produce and improve a
playable primary artifact with clear user-facing controls, usable assets,
review strictness, and a path to attach updated mechanics, sound, or source
material. The product improvement is generic: better protocol design, resource
ingress, primary outcome surfacing, and review quality.

### Manufacturing Analytics

Use analytics runs to prove data readiness, chart-first workflows, drilldowns,
recommendations, evidence, and non-technical usability.

### Risk Decision Engine

Use the payments/onboarding risk engine to prove the complete runnable-artifact
stack: Java/Maven prepared package, browser UI, backend APIs, runtime manifest,
Registry-routed UI/API paths, scenario submission, audit/explainability output,
review evidence, package download, lifecycle cleanup, Telegram access, and real
Safari proof.
