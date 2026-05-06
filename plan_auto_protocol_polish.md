# Auto Protocol Polish Plan: Runnable Artifacts, Honest Review Evidence, Reachable Links, and Fast Tests

## Status

Implemented in this branch as the runnable-artifact polish workstream. Keep this
document as the execution record and QA checklist for future refinement.

The prerequisite Auto Protocol closeout was completed before this workstream:
user/developer docs were updated, Telegram Web was verified in real Safari, and
the existing Auto Protocol lifecycle remained shared between Registry and
Telegram.

## Problem Statement

Octopus can now generate, publish, and run serious protocols through Registry and Telegram, and the Auto Protocol work has moved in the right direction: the model-backed planner can produce requirement-specific stage graphs, reviewers can send work back, primary artifacts are surfaced more prominently, and generated runs can produce nontrivial packages such as the payments and onboarding risk engine.

The remaining product gap is that a serious output is still treated too much like stored files. The risk-engine run produced a Java/Maven backend, seed data, tests, docs, and a static operator UI. The final run view correctly showed the primary artifact and a verified output path, but opening the artifact landed the user on a directory listing. That is useful for developers, but it is not the commercial product experience we need.

For artifacts intended to be used, Octopus must expose them as runnable, testable systems:

- A browser game should open as a playable game.
- A static HTML tool should open directly as an application.
- A Java risk engine should expose a running operator UI backed by coherent APIs.
- A backend service should expose API documentation and stable routed endpoints.
- Users should be able to start, inspect, test, stop, archive, and delete these runtime instances without SSH, Docker knowledge, or log archaeology.

At the same time, multi-file artifacts must remain available as inspectable and downloadable packages. A live system is not a substitute for a zip archive. Users need both:

- Open or start the runnable artifact.
- Browse files.
- Download the complete package as a zip.

The platform also needs faster feedback. We cannot burn ten or more minutes on every local test run, and we cannot lower the quality bar by skipping tests. Octopus must support focused, fast tests during iteration and a full suite that is bounded enough for regular CI.

Baseline clarification from code review:

- Directory artifacts already support inline file serving, browse pages, and
  zip download through the existing protocol artifact content route.
- Directory artifacts with a package-root `index.html` already open that file
  inline when browse mode is not forced.
- The missing product capability is not basic zip/file serving. The missing
  capability is first-class runtime lifecycle and routing for artifacts that
  need a process, an API, a UI, health checks, logs, and user-visible start/stop
  controls.
- Telegram links already honor configured public Registry URL environment
  variables. The remaining requirement is consistent device-reachable runtime
  links, clear localhost-only warnings, and no new runtime links that bypass the
  existing public URL configuration path.

## Context and Lessons Learned

### Auto Protocol generation can produce serious outputs, but file storage is not enough

The payments and onboarding risk-engine protocol produced a credible package:

- Java 21 and Maven backend.
- Risk decision service.
- DSL/rules engine.
- Feature registry.
- Model catalog.
- Scenario packs for payments, onboarding, lending, and investor/lender onboarding.
- Audit and explainability outputs.
- Static operator UI assets.
- Maven tests and release evidence.

The package was valuable, but the default user experience exposed it as a folder. A nontechnical or product evaluator should not have to infer which file starts the app, what command runs the backend, what port is used, or how the UI talks to the API.

Current artifact serving already does the right thing for simple static
packages when `index.html` is at the artifact package root. This plan preserves
that behavior. It adds the missing runtime path for packages where the primary
outcome is not a root static file: API-backed systems, Java/Maven services,
multi-directory apps, and generated products whose UI must talk to a backend.

### Primary artifact surfacing improved, but the next click matters

The Runs UI now surfaces the primary outcome prominently. The next product step is to make the primary outcome actionable:

- If it is a runnable artifact, the primary action should be "Open app" or "Start app", not only "Open folder".
- If it is a package, "Download zip" must remain obvious.
- If it is a backend system, "API docs" and "Health" should be visible.
- If it is not runnable, the UI should say that plainly and provide browse/download actions.

### Review loops worked, but review evidence must become runtime-aware

The risk-engine run showed that review loops can work: one reviewer sent the DSL and feature model stage back, and the follow-up attempt was accepted after concrete improvements. That is the behavior we want.

For runnable artifacts, final acceptance must go further than checking files. Reviewers should exercise the runtime through Octopus-managed surfaces and record why they accepted or sent work back:

- Service started successfully.
- Health endpoint passed.
- UI opened.
- Core scenario executed.
- API response was meaningful.
- Audit/explainability evidence was produced.
- Tests passed.
- Known limits were recorded.

### Multi-file artifacts need three surfaces, not one

For any multi-file artifact, Octopus should support:

1. Open default entry, when one exists.
2. Browse contents.
3. Download zip.

For runnable artifacts, there is a fourth surface:

4. Start or open runtime instance.

The user should not lose package access because a runtime exists.

### Tests must be fast without becoming fake

The team has repeatedly hit the cost of long tests. The solution is not to avoid testing. The solution is to split and speed the test program:

- Fast unit and contract tests for local iteration.
- Focused integration tests for changed paths.
- A full suite that is parallelized, deterministic, and bounded for CI.
- Browser and Safari checks reserved for UX-critical flows, not every code edit.

### The bot container is the execution substrate

The platform should not simplify runnable artifacts until only static pages work. The bot container itself is the controlled execution environment. It is provisioned with the product toolchain and already trusted to execute agent work. Runnable artifacts should execute there, under policy and lifecycle controls, while Registry sources, routes, proxies, authenticates, and records state.

That means the risk-engine class of artifact is not a later stretch goal. It is a required proof case:

- The Java/Maven backend runs inside the bot container.
- The operator UI is reachable through Registry-routed URLs.
- The UI calls backend APIs through the routed path.
- Telegram links point at the same configured public Registry surface.
- Users can stop, archive, delete, browse, and download without touching Docker.

## Product Principles

1. One honest path. Registry, Telegram, automation, and CLI surfaces use the same SDK contracts, Registry APIs, and run/artifact lifecycle.
2. No parallel artifact system. Runnable artifacts extend the existing protocol run artifact model and access path.
3. Stored artifact and runtime instance are distinct. Files are preserved as artifacts; live processes are managed runtime instances linked to those artifacts.
4. Multi-file artifacts always remain packageable. Directory artifacts provide browse and zip download regardless of runtime support.
5. User-facing APIs matter. A backend artifact intended for evaluation must expose coherent APIs, not only incidental debug endpoints.
6. Runtime lifecycle is first class. Start, health, status, logs, stop, archive, and delete are user-visible operations with permissions and audit events.
7. Links must work where users are. Telegram and Registry links use configured public or reachable base URLs, not hard-coded localhost unless that is the intended deployment.
8. Review decisions are evidence-backed. Accept and send-back decisions include rationale, attempt context, and runtime proof where relevant.
9. Fast tests protect quality. We reduce runtime through architecture, parallelism, fixtures, and focused suites, not by deleting meaningful coverage.
10. Documentation follows behavior. User docs and architecture docs must describe the actual surfaces, runtime lifecycle, link configuration, and testing model.
11. Capability is not sacrificed as a security shortcut. The platform secures runnable artifacts with bot-container execution, workspace scoping, runtime policy, resource limits, lifecycle controls, logs, and audit, not by reducing the product to static demos.

## Product Decisions

### Decision 1: Add first-class runnable artifact support

Octopus should introduce a first-class runtime capability for artifacts that are meant to be used interactively or through APIs.

The platform should recognize a runnable artifact through an artifact runtime manifest emitted with the artifact package. The canonical manifest file is `octopus-runtime.json` at the artifact package root. Registry parses and persists the manifest summary, but the package file remains the source artifact contract.

The manifest is not a new protocol format. It is metadata attached to a normal protocol artifact.

### Decision 2: Keep zip download for every directory artifact

Directory artifacts already support package download in the server path. This must become an explicit product guarantee:

- Multi-file artifact rows show "Download zip" or equivalent wording.
- Runtime-enabled artifacts still expose the zip.
- Telegram cards include package download links where reachable.
- API responses and docs make package download discoverable.

### Decision 3: Registry routes user access; bots run workloads

Registry should own public/user-facing URLs, auth, lifecycle state, and proxying. Bot runtime should execute the actual process inside the bot container where the workspace, dependencies, and generated files exist.

This preserves the architecture:

- SDK defines contracts and typed records.
- Registry persists state, exposes HTTP, enforces permissions, routes access, and proxies traffic.
- Bot runtime executes provider work and runtime processes through existing management plumbing.
- Telegram uses Registry APIs and links.

Registry must not become a second bot runtime. It must not run generated artifact processes. The bot must not invent its own user-facing routing surface.

For runtime traffic, Registry may proxy standard HTTP requests and responses to
the bot container through the existing management/control relationship. That
proxy is user-facing routing, not process execution. All artifact processes run
inside the bot container.

### Decision 4: Runnable artifacts need a runtime instance record

The existing protocol artifact record describes what was produced. It does not describe a live process. We need a persisted runtime instance record linked to:

- `protocol_run_id`
- `artifact_key`
- artifact content hash or observed path
- workspace reference
- owning user/actor context

This is not a duplicate artifact model. It is the missing lifecycle state for a running instance of an artifact.

### Decision 5: User-facing APIs are part of the artifact contract

For backend artifacts, the runtime manifest must declare at least:

- API base path.
- Health endpoint.
- UI entry path if present.
- OpenAPI/spec path when the artifact exposes APIs.
- Human-facing description of core flows.

Protocols and reviewers should treat missing or incoherent APIs as a quality issue when the requirement asks for an operable backend.

### Decision 6: Runtime actions are explicit user operations

The Runs UI must show clear controls:

- Start app.
- Open app.
- Open API docs.
- Check health.
- View runtime logs/status.
- Stop runtime.
- Archive runtime.
- Delete runtime.
- Download package.
- Browse files.

Controls appear according to runtime state and permissions.

### Decision 7: Runtime support must extend to Telegram

Telegram should not receive dead localhost links. It should receive Registry-routed links using the configured public base URL.

Existing Telegram protocol links already prefer `BOT_REGISTRY_PUBLIC_URL`,
`OCTOPUS_REGISTRY_PUBLIC_URL`, or `REGISTRY_PUBLIC_URL` when configured. Runtime
links must use the same source of truth instead of adding another link builder.
In localhost-only mode, Telegram must either label the link as host-local or
avoid presenting it as remotely usable.

Telegram cards for runnable artifacts should show:

- Open app.
- API docs, when available.
- Download zip.
- Runtime status.
- Stop/archive actions where safe and authorized.

### Decision 8: Final review should exercise runtime when declared

If an artifact declares a runtime, final acceptance must include runtime evidence. A final reviewer should not accept solely because files exist.

Minimum acceptance evidence:

- Runtime start attempted through Octopus.
- Health checked.
- UI or API opened.
- At least one core flow exercised.
- Logs or evidence captured.
- Runtime limitations noted.

If the runtime cannot start, the reviewer should send back unless the artifact contract explicitly says it is not runnable.

This must be enforced as product state, not only prompt language. If a runnable artifact reaches final acceptance without linked runtime events for start, health, and smoke exercise, the engine should block acceptance or mark the run as needing runtime evidence.

Existing protocol records already retain task `summary`, task `full_text`,
transition decisions, review rounds, and previous review feedback. This plan
extends those records in place with runtime evidence references. It must not add
a separate review-history model that can diverge from protocol transitions.

### Decision 9: Artifact runtime cleanup is part of platform hygiene

Runtime instances should not accumulate indefinitely. Product policy should define:

- Default idle timeout.
- Max runtime duration.
- Disk retention.
- Archive semantics.
- Delete semantics.
- Audit retention.

Stop should terminate the live process without deleting artifacts. Archive should hide or freeze the runtime record while preserving audit. Delete should remove runtime resources according to permissions and policy.

### Decision 10: Tests need a tiered execution strategy

We need a fast, trustworthy test strategy:

- Focused tests during implementation.
- Fast full suite target for CI.
- Runtime tests using fake or minimal runners for most cases.
- One representative end-to-end runtime flow with real HTTP routing.
- Browser/Safari QA matrix for release-critical UI behavior.

### Decision 11: Runtime commands remain expressive but policy-scoped

Runnable artifacts need enough expressive power to run real software. Octopus should not replace this with static-only behavior or narrow adapters that cannot run the risk-engine class of system.

The runtime manifest may declare a `start_command`, but the bot runtime executes it only inside the bot container and only after policy validation:

- working directory must resolve inside the artifact/workspace scope
- ports are allocated by the supervisor, not chosen freely by the artifact
- environment variables are allowlisted or generated by the supervisor
- runtime duration and idle limits are enforced
- process group cleanup is mandatory
- logs are captured
- network behavior follows deployment policy

This is the product/security boundary: flexible execution in a controlled bot container, never arbitrary execution in Registry or on the host.

### Decision 12: First runtime slice must support real HTTP UI and API systems

The first implementation must support:

- static HTML/apps/games
- Java/Maven services with browser UI and JSON APIs
- Node and Python apps when the generated artifact declares them and the bot image provides the toolchain
- generic process/binary execution under the same bot-container policy

Registry proxying must support normal browser and API traffic: HTML, JS, CSS, images/assets, JSON APIs, common HTTP methods, request bodies, response headers, redirects, and health checks. Streaming and WebSocket behavior must be decided in Phase 1 for artifacts that declare those transports, but standard HTTP UI/API support is required for the first probe.

## Target User Experience

### Registry Runs UI

When a run finishes with a runnable primary artifact, the run detail should show:

- Primary outcome card at the top.
- Runtime state: not started, starting, running, unhealthy, stopped, archived, failed.
- Primary action:
  - "Open app" if running.
  - "Start app" if not running.
  - "Restart app" if failed or stopped and restart is allowed.
- Secondary actions:
  - API docs.
  - Health.
  - Logs/status.
  - Browse files.
  - Download zip.
  - Stop.
  - Archive.
  - Delete.

The directory browser remains available, but it is no longer the default experience for artifacts with runnable entry points.

### Artifact Browser

For directory artifacts:

- Header shows package name and artifact key.
- "Open default" opens the runtime or default file when meaningful.
- "Browse files" stays available.
- "Download zip" is always visible.
- If a runtime manifest is present, the directory browser links back to "Open app" and "Runtime status".

### Telegram

For runnable artifacts, Telegram messages should include:

- Primary outcome name.
- Status.
- Open app link.
- Download package link.
- API docs link if available.
- Stop/archive action if appropriate.

Telegram should use configured public URLs and should never emit `127.0.0.1` unless the deployment explicitly declares localhost-only use.

### Review and Audit View

Run detail and exports should show:

- Decision: accept, revise, block, fail.
- Summary.
- Full rationale.
- Attempt number.
- What changed since previous attempt when applicable.
- Runtime evidence:
  - start result
  - health result
  - UI/API smoke result
  - logs or captured output

## Architecture Overview

### Existing path to extend

Current path:

1. Protocol run executes stages.
2. Stage produces artifact observations.
3. Registry records protocol artifacts.
4. UI and Telegram link to artifact content.
5. Artifact server returns file, directory listing, preview, or zip.

Target path:

1. Protocol run executes stages.
2. Stage produces artifact observations and a runtime manifest when the artifact is runnable.
3. Registry records protocol artifacts.
4. Registry validates runtime manifest for runnable artifacts.
5. User can browse/download stored artifact.
6. User can start a runtime instance linked to the artifact.
7. Bot runtime starts the process inside the bot container.
8. Registry exposes stable routed UI/API URLs.
9. Runtime events, health, logs, and lifecycle actions are persisted.
10. Reviewers and users exercise the runtime through Registry/Telegram links.

### New or extended SDK contracts

Add typed SDK records for runtime metadata and lifecycle. Use these records under the existing protocol/artifact SDK namespace:

- `ProtocolArtifactRuntimeManifestRecord`
- `ProtocolArtifactRuntimeEndpointRecord`
- `ProtocolArtifactRuntimeCommandRecord`
- `ProtocolArtifactRuntimeInstanceRecord`
- `ProtocolArtifactRuntimeEventRecord`
- `ProtocolArtifactRuntimeHealthRecord`
- `ProtocolArtifactRuntimeActionRequestRecord`
- `ProtocolArtifactRuntimeActionResultRecord`

These records should live under the existing protocol/artifact SDK area, not a separate product module.

Manifest fields should include:

- `runtime_kind`: `static`, `node`, `python`, `java`, `binary`, or `process`.
- `working_directory`.
- `start_command`.
- `environment`.
- `internal_port`.
- `health_path`.
- `ui_path`.
- `api_base_path`.
- `api_docs_path`.
- `openapi_path`.
- `readiness_timeout_seconds`.
- `idle_timeout_seconds`.
- `max_runtime_seconds`.
- `resource_limits`.
- `required_files`.
- `package_entry_label`.
- `description`.
- `transport_requirements`: standard HTTP, streaming HTTP, websocket, or other declared transport needs.

Do not add UI-only synthetic fields that are not persisted. If the UI needs runtime state, persist it.

### Registry persistence

Add a real persistence layer for runtime instances and events. Schema:

- `protocol_artifact_runtime_instances`
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

- `protocol_artifact_runtime_events`
  - `runtime_event_id`
  - `runtime_instance_id`
  - `protocol_run_id`
  - `artifact_key`
  - `event_kind`
  - `actor_ref`
  - `message`
  - `payload_json`
  - `created_at`

This is the minimum state needed for user-visible lifecycle and audit. It does not replace protocol artifacts.

### Registry HTTP API

Add API endpoints under the existing protocol run artifact namespace:

- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/start`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/stop`
- `POST /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/archive`
- `DELETE /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/events`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/logs`
- `GET /v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/health`

Add routed runtime access paths:

- `/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/app/...`
- `/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/api/...`

Exact path naming can follow existing Registry conventions. The important requirement is one stable, authenticated, Registry-owned URL space.

Blocked/error responses must follow the existing product requirement:

- stable error code
- human message
- validation summary
- blocker list
- warning codes
- explicit next-step guidance

### Registry to bot runtime orchestration

Use existing management/client patterns to ask the bot runtime to start and stop runtime processes inside the bot container. Do not add a direct ad hoc SSH or Docker path from the UI.

Runtime start flow:

1. Registry validates user permission and artifact visibility.
2. Registry resolves artifact path and runtime manifest.
3. Registry creates or updates runtime instance state to `starting`.
4. Registry sends a typed runtime start request through existing bot management transport.
5. Bot validates the manifest against local workspace and runtime policy.
6. Bot starts the process with a supervised process group.
7. Bot reports process reference, internal port, logs path, and health.
8. Registry records state and exposes routed URL.

Runtime stop flow:

1. Registry validates permission.
2. Registry sends typed stop request.
3. Bot terminates the process group cleanly.
4. Registry records stopped state.

Runtime delete flow:

1. Stop if running.
2. Remove runtime process metadata and ephemeral runtime files according to policy.
3. Preserve protocol artifact and audit unless delete policy explicitly includes them.

### Routing model

The first implementation should use Registry as the user-facing router:

- Registry owns auth.
- Registry validates runtime instance state.
- Registry proxies requests to the bot runtime internal endpoint.
- Registry rewrites paths according to the runtime manifest.
- Registry does not execute the artifact process.
- Bot runtime serves the generated process from the bot container.

This avoids exposing raw bot container ports to users and makes Telegram links stable.

Deployment-specific reverse proxies can sit in front of Registry, but the product contract remains Registry-owned routing and configured public URLs.

Standard HTTP UI/API routing is required in the first implementation. Registry routing must handle static assets and JSON API calls well enough for the risk-engine probe: HTML, JS, CSS, images, common HTTP methods, request bodies, redirects, response headers, health checks, and API errors. Streaming HTTP and WebSocket behavior must be specified during Phase 1 for artifacts that declare those transports.

### Public URL configuration

Add or verify configuration for:

- Registry bind host.
- Registry bind port.
- Public Registry base URL.
- Runtime public base URL if different.
- Telegram link base URL.
- Local-only mode flag.

Docs must explain:

- localhost-only deployment
- LAN/private network deployment
- public tunnel/reverse proxy deployment
- server deployment
- security tradeoffs of binding to all interfaces

User-facing links must use this configuration consistently.

## Auto Protocol Changes

### Runtime-aware planning

Auto Protocol should infer when the requested outcome is runnable:

- browser app
- game
- dashboard
- API service
- backend
- CLI plus web UI
- Java/Maven service
- Python/Node app

The planner should specify:

- expected runtime kind
- primary UI/API entry
- required runtime manifest
- smoke-test requirements
- final review runtime evidence

This must be requirement-specific and model-backed, not a hard-coded game/risk classifier.

### Runtime manifest artifact

When a protocol produces a runnable artifact, the implementation stage must produce a runtime manifest with the package.

For the risk engine, the package should include something like:

- `risk-decision-engine/octopus-runtime.json`
- `runtime_kind: "java"`
- `working_directory: "risk-decision-engine"`
- `start_command: "mvn exec:java -Dexec.mainClass=com.acme.risk.api.RiskServer -Dport=${PORT}"`
- `health_path: "/health"`
- `ui_path: "/"`
- `api_base_path: "/api"`
- `api_docs_path: "/api/docs"` or equivalent
- `readiness_timeout_seconds`
- `required_files`

For a static game:

- `runtime_kind: "static"`
- `working_directory`
- `ui_path: "/index.html"` or `/`
- asset integrity list

The manifest is required for process-backed runtimes and recommended for static
packages. A static package with a root `index.html` can still open through the
existing artifact content behavior. Adding a manifest makes its lifecycle,
Telegram actions, and review evidence explicit.

### Stage and review guidance

Generated protocols that promise runnable systems should include:

- Design stage for user-facing API and UI.
- Implementation stage that builds the runtime.
- Integration/test stage that starts it and records evidence.
- Final review stage that exercises it through the runtime surface.

Do not add several late reviewers after the primary artifact stage. The main artifact should be produced at the final work stage or second-to-last declared stage, followed by one final adversarial acceptance stage unless the planner has a clear reason for a second final gate.

### Primary artifact semantics

Primary artifact metadata should indicate:

- stored artifact key
- package download availability
- runtime manifest availability
- runtime entry action
- final reviewer evidence artifact

The Runs UI should use this to decide primary actions.

## Registry UI Implementation Plan

### Runs UI primary artifact card

Extend the primary artifact panel to show:

- Artifact status.
- Runtime status.
- Open app or Start app.
- API docs.
- Health.
- Logs/status.
- Browse files.
- Download zip.
- Stop.
- Archive.
- Delete.

Use clear labels. Avoid dumping raw paths as the dominant content. Paths can remain visible under details or copy actions.

### Artifact content page

Update directory artifact index pages:

- Rename "Download package" to "Download zip" where appropriate.
- If runtime manifest exists, show "Open app" or "Start app".
- If an `index.html` exists inside a known static app folder, surface it as a default entry.
- Keep browse table for developers.

### Runtime status panel

Add a compact runtime status panel:

- state
- started time
- last health check
- public URL
- owning run
- resource limits
- recent events

### Narrow UI

The narrow Runs UI must remain usable:

- Runtime controls wrap cleanly.
- Primary action remains visible.
- Logs and events collapse behind disclosures.
- Long paths and command text wrap.
- No horizontal overflow.
- Mobile nav overlay remains correct.

### Error UX

Runtime failures should be plain:

- "The app could not start because Maven is missing in the bot image."
- "The health endpoint did not respond within 30 seconds."
- "This artifact has no runtime manifest. You can still browse or download the package."

Each error should include next steps where possible.

## Telegram Implementation Plan

### Runtime cards

Telegram protocol/run messages should include runtime-aware primary artifact actions:

- Open app.
- API docs.
- Download zip.
- Runtime status.
- Stop runtime.

Use configured public base URL. If the deployment is localhost-only, Telegram should say that links are only usable from the host machine or should avoid sending misleading links.

### Commands or callbacks

Add callbacks using existing Telegram to Registry client patterns:

- Start runtime.
- Stop runtime.
- Runtime status.
- Download package.

Do not implement Telegram-only lifecycle behavior. Telegram calls Registry APIs.

## Bot Runtime Implementation Plan

### Runtime supervisor

Add a runtime supervisor in bot runtime using existing SDK contracts.

Responsibilities:

- Validate runtime manifest.
- Reserve/assign internal port.
- Start process in artifact working directory.
- Capture stdout/stderr logs.
- Track PID/process group.
- Check health.
- Stop process cleanly.
- Force kill after timeout if needed.
- Report lifecycle events to Registry.
- Keep execution inside the bot container; do not require nested Docker or host-level process control for the primary path.

### Tooling expectations

Bot images should include enough baseline tools for serious artifacts:

- shell utilities
- `rg`
- network tools useful for diagnostics
- compiler/build essentials
- Python
- Node where supported
- Java 21
- Maven
- ability to install libraries according to policy

Docs must state what is included and what agents are allowed to install.

### Security and policy

Runtime manifests should be checked against policy:

- allowed runtime kinds
- policy-scoped command execution inside the bot container
- max runtime duration
- max idle duration
- port range
- environment variable allowlist
- network policy
- filesystem scope

This is especially important because generated artifacts may run arbitrary code. The mitigation is not to remove the ability to run real software. The mitigation is to keep execution inside the bot container, restrict workspace and environment scope, allocate ports through the supervisor, capture logs, enforce duration/idle limits, and stop process groups cleanly.

## API Design Requirements for Generated Artifacts

When Auto Protocol builds a backend system, it should require meaningful user-facing APIs:

- versioned or clearly named routes
- health endpoint
- scenario/test endpoint where appropriate
- domain nouns in route names
- stable error shape
- explainability or audit retrieval where relevant
- API docs or at least a route index

For the risk engine class of artifact, expected APIs include:

- `GET /health`
- `GET /api/features`
- `POST /api/features`
- `GET /api/rules`
- `POST /api/rules`
- `GET /api/models`
- `POST /api/models`
- `GET /api/scenarios`
- `POST /api/decisions`
- `GET /api/audit`
- `GET /api/docs` or `GET /openapi.json`

These are examples for acceptance and testing, not hard-coded product-specific routes in Octopus.

## Review and Audit Implementation Plan

### Persist richer decision rationale

Ensure run transitions and stage executions persist:

- decision
- summary
- full rationale
- attempt number
- previous attempt reference
- what changed or what satisfied the reviewer
- runtime evidence references

If these fields already exist partially, extend them in place. Do not create a separate review-history path.

### Surface rationale

Registry Runs UI should show:

- why a reviewer accepted
- why a reviewer sent work back
- what changed on the accepted attempt
- runtime evidence for runnable artifacts

Telegram should summarize this in compact form with links to full evidence.

### Exports

Protocol run exports should include runtime and review evidence:

- runtime instance summaries
- runtime events
- review decisions
- review rationale
- artifact package references

## Lifecycle and Cleanup Plan

### Runtime lifecycle states

Use explicit states:

- `not_started`
- `starting`
- `running`
- `unhealthy`
- `stopping`
- `stopped`
- `failed`
- `archived`
- `deleted`

### Run and artifact operations

Operators and authorized users should be able to:

- terminate a run
- cancel a run
- archive a completed run
- delete allowed transient runtime resources
- stop a runtime
- archive a runtime record
- delete a runtime instance
- keep artifact files and audit according to retention policy
- clean bot workspace transient directories according to policy

### Cleanup jobs

Add cleanup policy enforcement:

- stop idle runtime instances
- remove expired runtime temp files
- remove expired bot workspace transient directories that are not part of retained artifacts or audit
- preserve artifacts and audit until explicit archive/delete rules apply
- report cleanup events

## Testing Plan

### Test tiers

Create or formalize test tiers:

1. `unit-fast`
   - SDK record validation.
   - Runtime manifest validation.
   - Artifact zip naming and content behavior.
   - Blocked response shapes.
   - Review rationale merge/serialization.

2. `registry-contract`
   - Runtime endpoints.
   - Artifact content browse/download/open behavior.
   - OpenAPI parity.
   - Public base URL link generation.

3. `bot-runtime-focused`
   - Fake runtime supervisor.
   - Start/stop/health lifecycle.
   - Log capture.
   - Failure paths.

4. `integration-focused`
   - Registry plus fake bot runtime.
   - Static HTML runnable artifact.
   - Minimal API-backed runnable artifact.
   - Stop/archive/delete.

5. `browser-focused`
   - Runs primary artifact panel.
   - Start/Open app action.
   - Download zip action.
   - Narrow layout.

6. `full`
   - All meaningful tests.
   - Parallel execution.
   - Bounded wall time.

### Performance requirements

Set a numeric budget in team policy. The target should be minutes, not tens of minutes.

Actions:

- Measure full-suite wall time before reorganizing fixtures or CI.
- Identify slow tests with timing output.
- Remove accidental sleeps.
- Replace live waits with polling on observed state.
- Use fake runtime supervisor for most tests.
- Share immutable fixtures safely.
- Parallelize with isolated DB schemas or cheaper fixture reset where proven equivalent. Current tests use a harness-owned Postgres database and broad autouse truncation, which is a likely bottleneck, but timing data must guide the actual changes.
- Keep one or two real integration tests for confidence.

### Acceptance tests for this program

Representative probes:

1. Static HTML/game artifact
   - package includes `index.html`
   - artifact page offers Open app and Download zip
   - app opens through Registry route
   - stop/archive controls are correct for static runtime

2. Java risk-engine artifact
   - package includes `octopus-runtime.json`
   - Registry starts runtime through bot supervisor
   - health endpoint passes
   - operator UI opens in Safari
   - UI calls backend APIs through routed path
   - scenario decision works
   - audit/explainability visible
   - package zip downloads
   - runtime stops cleanly

3. Telegram reachability
   - Telegram card link opens configured Registry URL
   - no accidental localhost link in public mode
   - runtime status and package download links work

4. Review evidence
   - final reviewer records runtime evidence
   - send-back reason is visible
   - accepted-after-revision explanation is visible

5. Cleanup
   - stopped runtime no longer serves app
   - artifact package remains downloadable
   - audit remains available

## Documentation Plan

Update user-facing docs:

- What a primary artifact is.
- Difference between browse, download zip, and open app.
- How to start and stop runnable artifacts.
- How to use a generated API-backed artifact.
- How Telegram links work.
- What to do when a runtime fails to start.

Update developer docs:

- Runtime manifest contract.
- SDK records.
- Registry APIs.
- Bot runtime supervisor.
- Routing and public URL config.
- Security and cleanup policy.
- Test tiers and expected commands.

Update architecture docs:

- Stored artifact vs runtime instance.
- Registry routing responsibility.
- Bot execution responsibility.
- Lifecycle state model.
- Event and audit model.

## Implementation Phases

### Phase 1: Baseline audit and contract finalization

1. Audit existing artifact content paths:
   - file response
   - directory listing
   - zip download
   - preview
   - protocol run artifact API
   - task artifact API

2. Audit existing run lifecycle and review evidence:
   - stage execution records
   - transitions
   - decisions
   - rationale fields
   - exports

3. Audit existing Registry to bot management transport.

4. Define SDK records for runtime manifests, instances, events, and action results.

5. Define exact HTTP routes and OpenAPI schema.

6. Confirm supported runtime kinds for the first implementation: `static`, `java`, `node`, `python`, `binary`, and `process`, all executed inside the bot container.

7. Define Registry proxy scope for standard HTTP UI/API routing required by the risk-engine probe.

8. Define OpenAPI regeneration/check behavior for CI when contracts change.

Acceptance:

- Written contract aligns with existing architecture.
- No parallel artifact serving path is proposed.
- Existing browse/download behavior remains preserved.
- The plan explicitly rejects static-only runtime scope.
- The risk-engine class of Java/Maven UI/API artifact remains a required first probe.

### Phase 2: Zip/package polish for multi-file artifacts

1. Make directory artifact zip download explicit in UI labels.
2. Ensure every multi-file artifact exposes Download zip from:
   - Runs primary artifact card
   - stage output rows
   - artifact directory page
   - Telegram card
3. Improve directory artifact index page:
   - readable title
   - Open default when meaningful
   - Download zip
   - file browse table
4. Add tests for directory zip behavior.

Acceptance:

- Multi-file artifact can always be downloaded as zip.
- Runtime-enabled artifacts still expose zip.
- No regression to file preview or browse.

### Phase 3: Runtime manifest validation and persisted runtime instances

1. Add SDK manifest and runtime instance records.
2. Add DB migration for runtime instances and runtime events.
3. Add store methods:
   - get runtime manifest for artifact
   - create runtime instance
   - update runtime state
   - append runtime event
   - list runtime events
4. Parse runtime manifest from artifact package.
5. Validate manifest against policy.
6. Add blocked responses for invalid/missing manifest.

Acceptance:

- Runtime metadata is persisted.
- UI does not rely on non-persisted synthetic fields.
- Invalid manifests produce human-readable errors.

### Phase 4: Bot runtime supervisor through SDK/management path

1. Add typed management request/response for:
   - start artifact runtime
   - stop artifact runtime
   - health check
   - log tail
2. Implement bot-side supervisor.
3. Start processes in isolated process groups.
4. Capture logs.
5. Poll health.
6. Report events to Registry.
7. Enforce runtime policy.

Acceptance:

- Registry does not shell directly into bots.
- Bot runtime owns process execution.
- Runtime processes execute inside the bot container.
- Start/stop/health work with static, Java/Maven UI/API, and process-style artifacts.

### Phase 5: Registry runtime APIs and routing

1. Add runtime lifecycle HTTP endpoints.
2. Add Registry-routed app/API proxy path.
3. Attach auth and permissions.
4. Implement health/log/status endpoints.
5. Ensure public base URL generation is consistent.
6. Update OpenAPI.
7. Add CI check that generated OpenAPI matches live route contracts.

Acceptance:

- User can start runtime from Registry API.
- User can open routed UI/API path.
- User can stop runtime.
- OpenAPI matches live behavior.
- Registry-routed standard HTTP UI/API traffic works for the risk-engine probe.

### Phase 6: Runs UI and artifact browser

1. Extend primary artifact card with runtime actions.
2. Add runtime status panel.
3. Add runtime logs/events disclosure.
4. Keep browse and download zip actions visible.
5. Update directory artifact page to link runtime when available.
6. Verify wide and narrow Safari layouts.

Acceptance:

- Nontechnical user sees Open app/Start app first for runnable artifacts.
- Download zip remains obvious.
- Narrow layout has no horizontal overflow.
- Runtime errors are understandable.

### Phase 7: Telegram runtime actions and reachable links

1. Add runtime status/action buttons to Telegram cards.
2. Use configured public Registry/runtime base URL.
3. Add warning behavior for localhost-only deployments.
4. Add start/stop/status callbacks through Registry API.
5. Add tests for link generation.

Acceptance:

- Telegram user can open a runnable artifact link when deployment is configured for reachable access.
- Telegram does not emit misleading localhost links in public mode.

### Phase 8: Auto Protocol runtime-aware generation and review evidence

1. Update planner prompt/contract to identify runnable outcomes.
2. Require runtime manifest when generated outcome is runnable.
3. Add runtime smoke-test requirements to implementation/review stages.
4. Update final review instructions to exercise runtime through Octopus.
5. Persist and surface runtime evidence in review rationale.
6. Enforce final acceptance blocking when runnable artifacts lack linked start, health, and smoke evidence.
7. Add tests with model-planner fixtures for static and API-backed runnable outcomes.

Acceptance:

- Auto Protocol for a browser game produces runnable static manifest.
- Auto Protocol for risk-engine style backend produces runtime manifest and API/UI expectations.
- Final review acceptance includes runtime evidence.
- Final review cannot silently accept a runnable artifact with no runtime evidence.

### Phase 9: Lifecycle, cleanup, and operations

1. Add stop/archive/delete runtime operations.
2. Add retention policy.
3. Add cleanup job.
4. Add operator docs.
5. Add run export runtime evidence.
6. Add bot workspace transient-directory cleanup policy.
7. Add permission tests.

Acceptance:

- Runtime can be stopped without deleting artifacts.
- Artifact package remains downloadable after stop.
- Archive/delete semantics are clear and tested.
- Bot workspace cleanup does not delete retained artifacts or audit evidence.

### Phase 10: Test performance program

1. Capture current full-suite timings.
2. Identify slowest tests.
3. Add test markers or scripts for focused tiers.
4. Parallelize safe tests.
5. Remove accidental sleeps and replace with state polling.
6. Add fake runtime supervisor for most lifecycle tests.
7. Keep real integration tests for the static artifact and Java/Maven risk-engine style artifact.
8. Add OpenAPI regeneration/check gate.
9. Set CI wall-time budget.

Acceptance:

- Developers can run focused tests quickly.
- Full suite remains meaningful and bounded.
- Runtime/artifact behavior is protected by tests.

### Phase 11: Documentation and QA matrix

1. Update user docs.
2. Update architecture docs.
3. Update protocol guide.
4. Add runtime artifact examples:
   - static app/game
   - Java API-backed app
5. Add QA matrix for:
   - Registry
   - Telegram
   - runtime artifacts
   - narrow Safari
   - public links
   - cleanup

Acceptance:

- Docs match actual behavior.
- QA matrix is repeatable by a human tester.

## Acceptance Criteria

The plan is complete when:

1. Multi-file artifacts always expose zip download.
2. Runnable artifacts declare a runtime manifest.
3. Registry validates and persists runtime state.
4. Bot runtime starts/stops artifact processes through SDK/management contracts.
5. Registry routes UI/API access through stable authenticated URLs.
6. Telegram links use configured public base URLs.
7. Runs UI makes runnable primary artifacts obvious and usable.
8. Users can start, open, test, stop, archive, and delete runtime instances according to permissions.
9. Final reviewers exercise runnable artifacts and persist rationale/evidence.
10. Review send-back and acceptance reasons are visible in Registry, Telegram, and exports.
11. Directory browse and zip download remain available for every multi-file artifact.
12. Tests cover SDK, Registry, Bot runtime, Telegram, UI, routing, lifecycle, and cleanup.
13. Full suite has a defined wall-time budget and focused suites support fast local iteration.
14. Documentation explains runtime artifacts, links, lifecycle, cleanup, and tests.
15. The risk-engine class of Java/Maven backend plus browser UI runs inside the bot container and is reachable through Registry and Telegram URLs.
16. OpenAPI contract checks fail CI when route behavior and docs drift.

## Non-Goals

These are not part of this plan:

- A second artifact storage model.
- Telegram-only runtime behavior.
- Raw Docker port instructions as the primary user experience.
- Hard-coded domain behavior for games, risk engines, manufacturing, fintech, or any single example.
- Hiding package files because a runtime exists.
- Deleting audit evidence as part of normal stop.
- Reducing test coverage to make tests appear faster.
- Static-only runtime scope that cannot run real backend systems.
- Running generated artifact processes inside Registry.

## Open Implementation Questions

These must be answered during Phase 1 before implementation proceeds:

1. Which bot owns a runtime when multiple agents contributed to the artifact?
   Initial rule: use the agent that produced the artifact when known; otherwise
   use the run entry agent. Persist the selected bot/agent on the runtime
   instance so future stop/health/proxy actions do not re-infer ownership.
2. What port range should the runtime supervisor reserve?
   Initial rule: supervisor allocates from a configurable bot-local range and
   never trusts a manifest-selected public port.
3. How should Registry proxy streaming responses and websockets for artifacts
   that declare those transports?
   Initial rule: standard HTTP UI/API is required first. Unsupported streaming
   or websocket declarations produce a clear blocked response rather than a
   broken link.
4. What is the default idle timeout?
   Initial rule: use conservative runtime policy defaults in the SDK record and
   persist them per instance.
5. What public URL config is required for Telegram links in local deployments?
   Initial rule: reuse the existing Registry public URL environment variables
   and show localhost-only language when the resolved base is localhost.
6. Which actors may start, stop, archive, or delete runtime instances?
   Initial rule: use the same protocol-run visibility/access path for start and
   status; restrict delete/archive to actors that can mutate the run/artifact.
7. How much runtime log content is persisted versus streamed from bot workspace?
   Initial rule: persist event summaries and bounded log tails; keep full logs
   in the bot workspace while the runtime exists.
8. What is the CI wall-time budget for the full suite?
   Initial rule: measure first, then set a budget in team policy before changing
   CI gates.

## First Representative Probe

Use the payments and onboarding risk engine as the first serious probe because it exercises the complete problem:

1. Auto Protocol generates a risk-engine protocol from a high-level requirement.
2. Protocol produces Java/Maven package with operator UI, backend APIs, seed data, docs, tests, and runtime manifest.
3. Runs UI shows primary outcome with:
   - Start app
   - Open app
   - API docs
   - Health
   - Browse files
   - Download zip
   - Stop/archive/delete
4. Registry starts the runtime through the bot.
5. Safari opens the operator UI through Registry route.
6. UI submits a scenario decision through routed API.
7. Audit/explainability result appears.
8. Final reviewer records runtime evidence.
9. User downloads zip.
10. User stops runtime.
11. Artifact remains browseable and downloadable.

This probe is not a hard-coded domain. It is a demanding example that proves the generic runtime-artifact capability.
