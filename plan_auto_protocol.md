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

Known open product gap:

- File and attachment ingress is not yet a coherent SDK-owned product path.
  Telegram can stage photo/document attachments, but Registry Auto Protocol,
  manual run launch, improve-run, and conversation surfaces do not expose a
  shared upload/resource path. Future Slack, WhatsApp, and other bot
  implementations must not copy Telegram-specific attachment behavior.

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
| Shared file/resource ingress | Gap identified; Telegram has a local attachment path, Registry does not | Add SDK resource contracts, Registry upload/attach UX, channel adapter normalization, runtime materialization, tests, docs, and real-surface proof |

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

## Implementation Sequence

### Phase 1: Keep One Plan And One Contract

- Maintain this file as the single plan.
- Delete obsolete split plan files.
- Keep status and ledger updates factual and tied to product proof.

### Phase 2: SDK File Resource Contract

- Add shared resource models, metadata, access policy, retention state, and
  materialization interfaces.
- Rationalize Telegram attachment staging behind the shared SDK contract.
- Ensure Registry delivery/conversation paths can carry resources instead of
  empty attachment tuples.
- Add focused tests for model serialization, materialization policy, and
  transport normalization.

### Phase 3: Registry Resource APIs And UI

- Add upload/list/select/attach/remove resource APIs.
- Add user-friendly attach controls to Auto Protocol create/revise, manual
  protocol design, run launch, improve-run, and conversations.
- Show attached resources in session/run/conversation context.
- Prevent uploads from becoming artifact outputs unless a run explicitly
  produces them.

### Phase 4: Channel Adapter Parity

- Keep Telegram native uploads working through the same resource path.
- Make future bot implementations depend on SDK resource interfaces, not
  Telegram-specific helpers.
- Ensure channel limitations are surfaced as capability metadata, not new
  product branches.

### Phase 5: Auto Protocol Uses Resources

- Include resource summaries in semantic planning context.
- Let generated protocols request, validate, and consume attached resources as
  run inputs.
- Ensure improve-run can use new files to improve existing outcomes, such as
  updated game mechanics, sound assets, datasets, docs, or code bundles.

### Phase 6: Runtime, Review, And Lifecycle Hardening

- Preserve prepared-artifact runtime policy.
- Keep review acceptance tied to runtime/evidence, not launch alone.
- Complete cleanup dry-run proof and workspace-wipe recovery proof.
- Keep archive/delete behavior separate for runs, runtimes, input resources,
  output artifacts, agents, skills, and protocols.

### Phase 7: Tests, Docs, Deployment, Proof

- Add focused tests for every regression touched.
- Use logs to verify progress instead of arbitrary sleeps.
- Use real Safari for release-critical Registry UI proof.
- Verify Telegram Web or equivalent real bot surface for channel behavior.
- Deploy to `/Users/tinker/octopus` after commit/push when implementation work
  is complete.

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
