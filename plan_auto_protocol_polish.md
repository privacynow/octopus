# Auto Protocol Polish Plan: Runnable Artifacts, Honest Review Evidence, Reachable Links, and Fast Tests

## Status

Implemented in `feature/auto_protocol`, deployed to the `/Users/tinker/octopus`
checkout, and live-verified in Safari across Registry and Telegram for the
prepared Java risk-engine artifact run `d38dab75b929405a9e4a3f1407491e76`.

This document is now the mandatory execution plan for finishing the runnable
artifact and Auto Protocol polish work. The work is not complete until every
acceptance criterion below is implemented, tested, documented, deployed, and
verified through the real Registry and Telegram surfaces.

Already implemented and covered by focused tests:

- Registry can persist artifact runtime instances and events.
- Bot runtime can start, fetch, health-check, log, and stop artifact processes
  through typed SDK/management contracts.
- Registry routes runnable artifact UI/API traffic through stable `/runtime/...`
  URLs instead of exposing raw bot ports.
- Directory artifacts still expose browse/open/download behavior, including zip
  download.
- Registry run detail surfaces a primary outcome card with Start/Open/Stop,
  browse, and download actions; older runs without declared primary metadata get
  a generic primary-artifact fallback.
- Telegram can start, open, and stop runnable artifacts through Registry APIs.
- Static/browser runnable artifacts were previously verified in real Safari
  from Registry and Telegram; the current implementation pass must be verified
  again after deploy.

Remaining work is implementation plus live product proof, not alternate
implementation. Nothing is optional or deferred. The next complete bar is the
risk-engine class of artifact: a Java/Maven backend with a browser UI,
meaningful routed APIs, runtime manifest, smoke evidence, review evidence,
package download, lifecycle cleanup, useful run discovery, and a clear path to
improve an existing run, verified through Registry and Telegram.

## Completion Ledger

This ledger is the accountability mechanism for the plan. A backend route,
SDK record, prompt instruction, or UI button is not enough by itself. A row is
complete only when every column needed for that outcome is implemented,
documented, covered by focused tests, and verified through the human-facing
surface.

| Outcome | Backend Contract | Registry UI | Telegram | Engine/Store Enforcement | Docs | Focused Tests | Real Safari Proof |
|---------|------------------|-------------|----------|--------------------------|------|---------------|-------------------|
| Runtime manifest detection | Implemented | Implemented | Implemented through artifact cards | Implemented via manifest validation | Documented | Covered | Safari verified prepared `java -jar` manifest on `d38dab75b929405a9e4a3f1407491e76` |
| Start/open/stop runtime | Implemented | Implemented | Implemented | Implemented for lifecycle state | Documented | Covered | Safari verified Registry start/open/UI/API exercise and Telegram start/status/package delivery for the prepared Java artifact; stop controls remain existing lifecycle coverage |
| Health/logs/events visibility | Implemented | Implemented in runtime dialog | Status card implemented; detailed logs remain Registry-owned | Events persisted | Documented | Covered | Safari/Telegram status recorded healthy Java runtime event with HTTP 200 and product health JSON |
| Archive/delete runtime | Implemented HTTP | Implemented in runtime dialog | Registry-owned destructive lifecycle; Telegram links back to artifacts | Stop-before-archive/delete enforced | Documented | Covered | Pending current Safari proof |
| Package browse/download zip | Implemented | Implemented | Implemented fallback package link | Existing artifact path | Documented | Covered | Telegram Web delivered the `output` package and Registry served artifact routes for the prepared Java run |
| Runtime evidence in review | Prompt guidance present | Evidence visible through runtime dialog and run detail | Status linked from cards | Hard accept gate implemented | Documented | Covered | Product engine completed `d38dab75b929405a9e4a3f1407491e76` after recorded start, health, routed UI/API exercise, visible result, readiness matrix, and branding evidence |
| Runtime evidence in export | Implemented | N/A | N/A | Export payload includes runtime instances/events | Documented | Covered | Registry runtime events/exportable run state verified for `d38dab75b929405a9e4a3f1407491e76` |
| Runtime cleanup/retention | Bot reaper and Registry sweep implemented | Operator lifecycle visible through runtime dialog | N/A | Runtime expiry policy enforced | Documented | Covered | Pending current Safari proof |
| Fast/tiered tests | Focused runner and markers implemented | N/A | N/A | N/A | Documented | Focused tiers covered | N/A |
| Runs discovery and recency | Default API keeps human-generated runs visible and recency ordered | Default Runs view is recent-first with useful human filters | Recent run references resolve predictably | Store visibility avoids burying real user runs | Documented | Covered | Pending current Safari proof |
| Improve existing run | Reuses Auto Protocol revise session against the existing run's protocol | Run detail can generate/apply/publish/run an improvement protocol from run context | Telegram command can improve a selected run | No duplicate protocol generator or run model | Documented | Covered | Pending current Safari proof |
| SDK-backed agent awareness | SDK owns protocol/run/artifact/capability awareness records and prompt rendering | Registry conversations receive the awareness brief | Telegram conversations receive the same awareness brief; `/protocol` remains a shortcut | Registry is authority implementation, not a bot-specific side channel | Documented | Covered | Pending current Safari proof |
| Risk-engine Java/Maven proof | Prepared Java artifact generated through Auto Protocol with `java -jar target/risk-decision-engine.jar`; generic run-ready policy still blocks developer/build commands before dispatch | Registry/Safari proved routed UI/API, scenario execution, and runtime health for the prepared artifact | Telegram Web proved status, artifact package delivery, runtime start, and runtime health through Registry APIs | Acceptance gate and Registry start share the same run-ready manifest policy; product reviewer gate completed the run without Codex manually accepting or sending back | Documented | Focused start/acceptance/UI recovery regressions covered | Real Safari + Registry/Telegram logs prove prepared Java runtime `d38dab75b929405a9e4a3f1407491e76` is complete |

Every implementation phase below must update this ledger when the product
state changes. The ledger favors user outcomes over internal implementation
claims.

Latest proof note, 2026-05-07: the deployed Registry could start the
risk-engine artifact through the real runtime path, but the artifact manifest
used `mvn spring-boot:run`, and live logs showed Maven dependency resolution
during user start. That is not a run-ready artifact. The product now blocks the
same class of manifest at Registry runtime start, before dispatching to a bot,
using the same generic command policy already used by final acceptance. The
final acceptance gate no longer requires an operator to manually return this
class of work: when the protocol has a revise path, missing/invalid/non-run-ready
runtime manifests become an in-product revise transition with the blocker
details in the next stage input. The next risk-engine proof must regenerate or
revise the artifact through the real protocol path so its `start_command`
launches a prepared package such as `java -jar target/app.jar`.

Follow-up proof note, 2026-05-07: the deployed Registry UI was tested in real
Safari on the live risk-engine run
`2d44384b9cce4bebae814e2616fdd934`. Registry logs showed Safari loading the
current UI asset, making runtime status GETs, and issuing
`POST /v1/protocol-runs/2d44384b9cce4bebae814e2616fdd934/artifacts/produced_outcome/runtime/start`,
which returned `409 Conflict` before bot dispatch. The run detail kept `Start
app` enabled and surfaced the product blocker inline: Maven developer-mode
commands build or resolve dependencies at user start, so the artifact package
must be revised first. This proves the current non-run-ready artifact is handled
by product policy and UI, not by an operator manually sending work back. It does
not prove the regenerated prepared Java package, Registry-routed UI/API health,
or Telegram runtime lifecycle yet.

The prerequisite Auto Protocol closeout was completed before this workstream:
user/developer docs were updated, Telegram Web was verified in real Safari, and
the existing Auto Protocol lifecycle remained shared between Registry and
Telegram.

Prepared-artifact proof note, 2026-05-07: Auto Protocol generated the
risk-engine class through the real Registry path as run
`d38dab75b929405a9e4a3f1407491e76`. The produced artifact is a Java runtime
package with `octopus-runtime.json` at the package root and a run-ready
`start_command` of `java -jar target/risk-decision-engine.jar`; Maven remains a
build/test tool for this artifact, not the user-start path. Real Safari opened
the Registry-routed app, clicked `Run scenarios`, ran
`scn_pay_review_high_value_new_customer`, and Registry runtime events recorded
`GET /health`, `GET /api/v1`, `GET /api/v1/scenarios`,
`GET /api/v1/decisions`, `GET /api/v1/models`, and
`POST /api/v1/scenarios/scn_pay_review_high_value_new_customer/run` with HTTP
200 responses. Telegram Web then used the same Registry APIs to show run status,
list artifacts, deliver the `output` package, start the app on bot port `53137`,
and record a healthy Java runtime status. The final acceptance transition was
made by the product engine: `accept` by `protocol_engine/operator-session` after
runtime start, health, routed UI/API exercise, visible outcome evidence,
outcome-readiness matrix, and customer-facing branding evidence were present.
Codex did not manually click or issue accept/send-back.

## Problem Statement

Octopus can now generate, publish, and run serious protocols through Registry and Telegram, and the Auto Protocol work has moved in the right direction: the model-backed planner can produce requirement-specific stage graphs, reviewers can send work back, primary artifacts are surfaced more prominently, and generated runs can produce nontrivial packages such as the payments and onboarding risk engine.

The remaining product gap is that a serious output is still treated too much like stored files, and completed work is still too hard to find and improve. The risk-engine run produced a Java/Maven backend, seed data, tests, docs, and a static operator UI. The final run view correctly showed the primary artifact and a verified output path, but opening the artifact landed the user on a directory listing. The default run list also hid that run behind generated/audit filtering and regrouped the page in a way that felt random instead of recent-first. That is useful for developers debugging internals, but it is not the commercial product experience we need.

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
- Find the most recent meaningful runs without knowing hidden filters.
- Improve an existing run through Auto Protocol instead of manually rebuilding
  the protocol or patching the artifact.

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
12. Bot capabilities are SDK capabilities. Anything that makes an agent aware of Octopus protocols, runs, stages, artifacts, skills, tools, or workspace state must live behind SDK contracts so future bot implementations can implement the same behavior without copying Registry or Telegram code.

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

- One prominent app action at a time: `Start app` before a runtime exists, then `Open app`, `Status`, and `Stop` after it starts.
- API docs for every backend/API runtime.
- Download zip/package.
- A clear path back to the full artifact list.

Telegram must not render a dense grid of preview/open/send buttons for every artifact by default. Non-primary artifacts can stay in the text body with command/link fallbacks; the tappable buttons should privilege the primary runnable outcome and the safest next action.

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

Registry proxying must support normal browser and API traffic: HTML, JS, CSS,
images/assets, JSON APIs, common HTTP methods, request bodies, response headers,
redirects, and health checks. Streaming HTTP and WebSocket transports are not
part of this plan's supported runtime transport set; artifacts that declare them
must receive a clear blocked response instead of a broken link.

### Decision 13: Runs default to human recency, not implementation triage

The default Runs surface is a user history view. It should show meaningful
human-originated runs in newest-updated order, including Auto Protocol runs
created from Registry or Telegram. Generated/audit filtering remains available
for internal rehearsal, smoke, and blank/system runs, but it must not bury a real
customer-facing run that has a problem statement and a human surface origin.

Triage is still valuable, but it is an explicit focus mode, not the default
ordering model. A user should not need to memorize "show generated/audit runs"
or decode grouped sections to find the work they just ran.

### Decision 14: Existing runs can be improved through the same Auto Protocol path

Users must be able to take an existing run, describe what needs to improve, and
generate a revised protocol from that run context. This is not a new generator,
artifact patcher, or side-channel. Registry and Telegram both call the existing
Auto Protocol session lifecycle in `revise` mode against the run's protocol, with
the run objective, status, primary artifact, artifacts, and user improvement
request included as planning context.

The feature exists to improve product outcomes. If a risk-engine run lacks a
root runtime manifest, routed UI/API, smoke evidence, or current quality bar,
the next action should be "Improve this run" rather than "hunt through files and
manually rewrite the protocol."

### Decision 15: Agents receive SDK-backed Octopus awareness

Agents should be able to reason about Octopus itself: available protocols,
recent runs, stage status, primary artifacts, runnable outcomes, workspace
mounts, active skills, installed tools, and their high-trust container
capabilities. This must not be implemented as a Telegram-only help command,
a Registry-only prompt string, or a local shadow catalog inside each bot.

The SDK owns the awareness contract:

- typed records for agent capability, protocol catalog, run, stage, artifact,
  runtime, and action guidance summaries
- a port that future bot runtimes can implement without importing Registry
  internals
- a renderer that produces a compact provider-facing awareness brief
- clear guidance about what the agent knows, what it can do directly, and what
  actions are mediated by the current surface

The current implementation sources awareness from Registry through existing
SDK/RegistryClient ports. Registry remains the authority for persisted protocol
state. The bot runtime consumes SDK awareness and injects it into the shared
execution context, so Registry conversations, Telegram conversations, and future
bot transports receive the same product behavior.

Telegram is a required surface for this behavior. A human in Telegram should be
able to ask natural questions such as "what protocols are available?", "what did
the latest run produce?", "how do I improve that run?", or "what can this bot
install?" without memorizing a dense command protocol. The existing
`/protocol ...` commands and buttons remain useful shortcuts, but they are not
the only source of understanding.

## Target User Experience

### Registry Runs UI

The default Runs page should show recently updated meaningful runs first. The
primary filters should match human tasks:

- Recent.
- Needs attention.
- Running.
- Completed.
- With outcomes.
- From Telegram.
- From Registry.

Operational issue filters remain available for support workflows, but they
should not dominate the default experience.

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
  - Improve this run.

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
- A progressive app action: start first, open/status/stop only after the runtime exists.
- Download package link.
- API docs link for backend/API runtimes.
- Stop/archive action when a runtime instance exists and the user is authorized.
- Compact fallback links for supporting artifacts without turning the message into a button wall.

Telegram should use configured public URLs and should never emit `127.0.0.1` unless the deployment explicitly declares localhost-only use.

Telegram should also support improving an existing run without requiring users
to memorize protocol ids or recreate context. A user can select `latest`, a
recent index, or a run id/prefix, provide an improvement request, and receive the
normal Auto Protocol draft card with apply/publish/run actions.

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

Standard HTTP UI/API routing is required in this implementation. Registry
routing must handle static assets and JSON API calls well enough for the
risk-engine probe: HTML, JS, CSS, images, common HTTP methods, request bodies,
redirects, response headers, health checks, and API errors. Streaming HTTP and
WebSocket transports are not supported by this plan; artifacts that declare
those transports must receive a clear blocked response.

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

- Rename directory artifact controls from "Download package" to "Download zip".
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

Each runtime error must include a next step, or an explicit statement that no
user action is available.

## Telegram Implementation Plan

### SDK-backed awareness in normal conversation

Normal Telegram messages should receive the same SDK-backed Octopus awareness
brief as Registry conversations. A user should be able to ask about available
protocols, recent runs, run outcomes, artifacts, runtime links, installed tools,
sudo/container access, and improvement paths in plain language.

Telegram-specific behavior remains thin:

- The shared execution context supplies awareness.
- Telegram presenters and `/protocol ...` commands remain action shortcuts.
- Telegram does not maintain a separate protocol catalog or run memory.
- The awareness brief should mention the shortest useful Telegram command only
  when an action needs the surface to mediate it.

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
- Improve run.

Do not implement Telegram-only lifecycle behavior. Telegram calls Registry APIs.

## Bot Runtime Implementation Plan

### SDK-backed awareness service

Add an SDK-owned awareness service and bot runtime port.

Responsibilities:

- Summarize the current agent/container capability state without exposing
  secrets.
- Summarize configured workspace mounts and active project policy.
- Summarize available and active runtime skills through SDK skill catalog
  interfaces.
- Summarize launchable protocols and recent meaningful runs through SDK
  protocol ports.
- Include primary artifact and runtime hints for recent runs when available.
- Render a compact provider-facing brief that can be prepended to every normal
  execution request.
- Fail closed to a short "awareness unavailable" note rather than blocking user
  work when Registry is temporarily unavailable.

Implementation boundaries:

- SDK defines records, ports, and rendering.
- The current app implementation wires the port to `RegistryClient` and
  `ProtocolService`.
- Registry is only the authority implementation; no bot should import Registry
  store internals or read Registry database tables directly for awareness.
- The provider process does not receive raw Registry tokens or secret
  environment variables. The bot runtime fetches awareness before invoking the
  provider and passes only safe summaries.
- The same awareness path is used by Registry and Telegram conversation turns.

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
- scenario/test endpoint for interactive backend artifacts
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

## Remaining Execution Sequence

The following phases replace the original implementation-phase checklist. They
start from the code already shipped in this branch and sequence the remaining
work to the final commercial bar. Do not split these into optional tracks. Each
phase must leave the product more coherent, preserve one path, and include
focused tests before moving on.

### Phase 0: Lock the shipped baseline

1. Re-audit the current branch against this plan:
   - SDK runtime records and ports.
   - Registry runtime store methods, routes, OpenAPI, and proxy paths.
   - Bot runtime supervisor and management transport.
   - Registry Runs UI primary artifact card.
   - Telegram runtime card/callback flow.
   - Docs and examples.
2. Mark implemented plan items in this file only when code, tests, and live QA
   prove them.
3. Confirm no duplicate runtime or artifact serving path was introduced.
4. Confirm all runtime state used by UI/Telegram is sourced from persisted
   runtime instance/event records or from current artifact records.

Acceptance:

- The branch has one runtime-artifact path: protocol artifact -> Registry
  runtime API -> SDK/management -> bot runtime -> Registry-routed URL.
- The shipped static/browser artifact flow remains working in Registry and
  Telegram.
- The working tree is clean before Phase 1 starts.

### Phase 1: Harden runtime manifests and artifact package contracts

1. Make `octopus-runtime.json` mandatory for every new Auto Protocol artifact
   that declares a process-backed or API-backed runnable outcome.
2. Keep the static `index.html` fallback for existing/simple static directory
   artifacts, but make new Auto Protocol static app/game outputs emit a manifest
   as well so lifecycle, Telegram actions, and review evidence are explicit.
3. Validate manifest fields in SDK and Registry:
   - runtime kind
   - working directory within artifact/workspace scope
   - start command for process-backed runtimes
   - UI path
   - health path
   - API base path and API docs path when an API is declared
   - smoke-test steps
   - required files
   - timeouts and resource policy
4. Return actionable blocked responses for invalid or missing manifests.
5. Update artifact content and primary artifact UI copy to distinguish:
   - static file open
   - runtime app open
   - browse files
   - download zip
6. Add focused tests for:
   - valid static manifest
   - valid Java/process manifest
   - invalid working directory
   - missing start command for process-backed runtime
   - missing API docs for API-backed runtime
   - missing smoke-test declaration

Acceptance:

- Serious runnable outputs cannot silently rely on directory browsing or
  incidental static fallback.
- Simple static artifacts remain usable.
- Users get a clear next step when a manifest is missing or invalid.

### Phase 2: Complete Registry runtime UX and artifact browser

1. Add a complete runtime status panel on the run detail primary artifact card:
   - state
   - start time
   - owning bot/agent
   - routed app URL
   - API base URL
   - API docs URL
   - health URL
   - last health summary
   - recent runtime events
   - recent bounded log tail
2. Add `Health`, `Logs`, `API docs`, `Archive`, and `Delete runtime` actions
   where the manifest and permissions allow them.
3. Keep `Start app`, `Open app`, `Stop app`, `Browse files`, and `Download zip`
   visible without forcing users into stage output details.
4. Update the directory artifact browser page to show:
   - app/runtime action when a runtime manifest exists
   - default static entry when the artifact has an indexable static entry point
   - download zip
   - readable file table
   - link back to run detail
5. Run wide and narrow Safari QA for:
   - completed run with runnable primary artifact
   - run with non-runnable artifact
   - invalid manifest
   - runtime failed to start
   - stopped runtime

Acceptance:

- A nontechnical user can find, start, inspect, stop, browse, and download the
  main outcome from the run detail without hunting through stage rows.
- Narrow Registry remains readable and has no horizontal overflow or button
  pileup.

### Phase 2A: Fix Runs discovery and existing-run improvement

1. Make the default Runs page recent-first:
   - use the backend recency order as the default display order
   - stop grouping the default list by triage state
   - keep issue/triage mode as an explicit focus
2. Make default run visibility human-centered:
   - show normal human-originated Registry and Telegram runs with problem
     statements even when historical data marked them hidden
   - keep blank, rehearsal, smoke, and generated/audit runs behind the explicit
     generated/audit toggle
3. Replace arbitrary default filters with human filters:
   - Recent
   - Needs attention
   - Running
   - Completed
   - With outcomes
   - From Telegram
   - From Registry
4. Add `Improve this run` to run detail:
   - reuse Auto Protocol create/revise/apply/publish/run APIs
   - target the selected run's protocol id
   - include the run objective, status, primary artifact, artifact summary, and
     user improvement request in the planning context
   - route Publish & Run to the new run detail
5. Add Telegram run improvement:
   - `/protocol improve-run latest <request>`
   - `/protocol improve-run <run id or recent index> <request>`
   - persist and render the resulting Auto Protocol session like every other
     Auto Protocol session
6. Add focused tests for:
   - default visibility of human-originated generated runs
   - hidden rehearsal/system runs staying hidden
   - Registry UI run filters and improve action wiring
   - Telegram improve-run payload construction
7. Verify in real Safari:
   - default Runs page shows the risk-engine class run without the generated
     toggle
   - list order is recent-first
   - narrow mode remains readable after generation
   - Improve this run creates an Auto Protocol session
   - Telegram improve-run creates the same kind of session

Acceptance:

- A user can find the run they just completed, understand the outcome, and ask
  Octopus to improve it without reconstructing protocol context manually.
- The improvement flow uses the canonical Auto Protocol session lifecycle from
  both Registry and Telegram.

### Phase 3: Complete Telegram runtime and public-link behavior

1. Make Telegram runtime messages progressive:
   - before start: primary artifact summary + `Start app` + `Download package`
   - after start: `Open app`, `Status`, `Stop`, `Download package`
   - for API artifacts: `API docs` and `Health`
2. Route every Telegram link through the same configured public Registry URL
   source used elsewhere.
3. Add localhost-only language when the configured base URL is localhost.
4. Add tests for:
   - public URL configured
   - localhost-only mode
   - start/status/stop callbacks
   - static artifact message
   - API-backed artifact message
5. Verify in real Safari with Telegram Web:
   - start runtime
   - open app
   - open API docs when present
   - stop runtime
   - download package

Acceptance:

- Telegram never presents a localhost link as remotely usable.
- Telegram users can execute the same runtime lifecycle as Registry users
  through Registry APIs, not Telegram-only behavior.

### Phase 3A: Add SDK-backed agent awareness to Registry and Telegram conversations

1. Add SDK records and ports for agent awareness:
   - agent identity and execution capability summary
   - workspace/project summary
   - toolchain and sudo availability
   - available and active skill summary
   - launchable protocol summary
   - recent run/stage/artifact/runtime summary
   - action guidance for run, improve, artifact, and runtime operations
2. Implement an SDK service that builds and renders the awareness brief from
   protocol and skill ports.
3. Implement the current bot runtime adapter using `RegistryClient`,
   `ProtocolService`, and runtime skill catalog interfaces.
4. Inject the rendered brief through the shared execution context before
   provider invocation, not through Telegram-only or Registry-only handlers.
5. Keep tokens and secrets out of provider context.
6. Ensure the brief is compact, fresh enough to reflect newly added protocols,
   and resilient to temporary Registry failures.
7. Verify both Registry and Telegram ordinary conversation turns can answer
   protocol/run/artifact/capability questions without the user memorizing
   command syntax.

Acceptance:

- Future bot implementations can implement the same awareness behavior by
  satisfying SDK ports.
- Current Registry and Telegram conversations receive the same awareness brief.
- The awareness brief mentions `/protocol` shortcuts in Telegram as shortcuts,
  not as the only knowledge path.
- New published protocols appear in subsequent agent awareness without copying
  files into the bot or maintaining a shadow catalog.
- Focused tests prove SDK summary rendering and shared execution-context
  injection.

### Phase 4: Make Auto Protocol runtime-aware in generation, revision, and validation

1. Extend the model planner contract so it must classify runnable outcomes and
   return runtime expectations:
   - runtime kind
   - manifest requirement
   - UI/API expectations
   - smoke-test steps
   - final review evidence requirements
2. Compile those expectations into the canonical protocol document:
   - implementation stage instructions
   - integration/smoke stage
   - final review stage
   - artifact definitions
   - primary artifact metadata
3. Add semantic validation so runnable protocols are not ready when:
   - no primary artifact is declared
   - runtime manifest is missing from the expected package
   - API-backed requirements lack API docs/health/scenario endpoints
   - final review is not instructed to exercise the runtime
   - primary artifact is buried before unnecessary late reviewers
4. Keep the logic generic. Do not hard-code games, risk engines, manufacturing,
   fintech, or any example domain into Octopus product code.
5. Add model-fixture tests for:
   - browser game/static app
   - Java/Maven API-backed system
   - non-runnable report/document package
   - revise path preserving runtime expectations
   - blocked generated protocol when runtime expectations are incomplete

Acceptance:

- Auto Protocol generates requirement-specific runnable workflows without the
  user manually prompting for runtime manifests, reviews, or smoke tests.
- The risk-engine class of prompt generates a Java/Maven UI/API workflow with
  manifest and smoke evidence requirements.

### Phase 5: Enforce runtime review evidence in the protocol engine

1. Extend existing stage execution, transition, and artifact evidence paths in
   place. Do not create a parallel review-history model.
2. Persist runtime evidence references:
   - runtime instance id
   - start event
   - health event
   - smoke-test result
   - API/UI path exercised
   - relevant log/event ids
3. Surface review evidence in:
   - Registry run detail
   - stage/decision detail
   - Telegram summary
   - run export
4. Enforce final acceptance for runnable artifacts:
   - final review cannot accept a declared runnable primary artifact unless
     linked runtime start, health, and smoke evidence exist
   - missing evidence creates a blocked/send-back condition with a clear message
   - non-runnable protocols are unaffected
5. Add tests for:
   - accept blocked with no runtime start
   - accept blocked with failed health
   - accept blocked with no smoke evidence
   - accept succeeds with complete evidence
   - send-back rationale preserved across attempts
   - export includes runtime/review evidence

Acceptance:

- A runnable artifact cannot be commercially “accepted” by prompt sympathy alone.
- The product can explain why work was accepted or sent back without reading bot
  logs.

### Phase 6: Complete lifecycle, retention, and cleanup

1. Finish user-facing operations:
   - stop runtime
   - archive runtime
   - delete runtime instance
   - terminate/cancel allowed runs
   - archive completed runs where product rules allow
2. Define and implement retention policy:
   - runtime idle timeout
   - maximum runtime duration
   - bounded log retention
   - bot workspace transient cleanup
   - artifact/audit retention
3. Add cleanup job or operator command that:
   - stops idle runtimes
   - removes expired runtime temp files
   - removes expired transient bot workspace files
   - preserves retained artifacts and audit
   - records cleanup events
4. Add permission tests for start, stop, archive, delete, and cleanup.
5. Document the lifecycle semantics in user and operator docs.

Acceptance:

- Users can try a runtime artifact and shut it down cleanly.
- Operators can keep workspaces from accumulating live processes or transient
  files without destroying retained artifacts or audit evidence.

### Phase 7: Build and prove the Java/Maven risk-engine probe

1. Use Auto Protocol from Registry to generate a risk-engine protocol from the
   high-level payments/onboarding/lending/investor-onboarding requirement.
2. Do not manually hard-code risk-engine behavior into Octopus.
3. Publish and run the generated protocol through the UI.
4. The protocol must produce a package with:
   - Java 21/Maven backend
   - browser operator UI
   - meaningful API routes
   - API docs or route index
   - seed/scenario data
   - audit/explainability output
   - tests/smoke evidence
   - `octopus-runtime.json`
   - downloadable zip
5. Start the runtime from Registry.
6. Open the operator UI through Registry routing in real Safari.
7. Submit a scenario decision through the UI/API.
8. Inspect audit/explainability output.
9. Stop the runtime from Registry.
10. Repeat the essential lifecycle from Telegram Web in real Safari:
    - start
    - open UI
    - open API docs/health
    - stop
    - download package
11. If the probe exposes a product gap, fix the product first, then rerun the
    probe. Do not patch the artifact directly as the solution.

Acceptance:

- The risk-engine class of artifact runs inside the bot container and is
  reachable through Registry-routed UI/API URLs.
- A nondeveloper can open the UI, exercise a decision flow, inspect evidence,
  download the package, and stop the runtime.

### Phase 8: Finish the fast, trustworthy test program

1. Capture current focused and full-suite timings.
2. Add formal test markers or scripts:
   - `unit-fast`
   - `registry-contract`
   - `bot-runtime-focused`
   - `integration-focused`
   - `browser-focused`
   - `full`
3. Replace accidental sleeps with polling on observable state.
4. Use fake runtime supervisors for most lifecycle tests.
5. Keep real integration tests for:
   - static browser artifact
   - Java/Maven UI/API artifact
6. Parallelize safe tests with proven DB isolation or cheaper fixture reset.
7. Add an OpenAPI regeneration/check gate so route/schema drift fails CI.
8. Set and enforce a full-suite wall-time budget in team policy.

Acceptance:

- Developers have fast focused tests that protect changed paths.
- Full CI remains meaningful, bounded, and aligned with product behavior.
- Runtime/artifact behavior is not protected only by manual Safari QA.

### Phase 9: Documentation and QA matrix closure

1. Update docs to match implemented behavior:
   - README
   - Getting Started
   - User Guide
   - Protocol Guide
   - Telegram Guide
   - Operations
   - Architecture
   - SDK Bot Development
   - examples
2. Add a repeatable QA matrix covering:
   - Registry static runnable artifact
   - Registry Java/Maven API-backed artifact
   - Telegram static runnable artifact
   - Telegram Java/Maven API-backed artifact
   - narrow Safari
   - public URL/local URL behavior
   - runtime start/open/health/logs/stop/archive/delete
   - package download after stop
   - review evidence enforcement
   - cleanup
3. Run the QA matrix in real Safari where it tests UI behavior.
4. Fix every product defect found by QA before declaring the plan complete.

Acceptance:

- Docs are progressive and accurate for nontechnical and technical users.
- A human tester can repeat the matrix without private context from this
  development thread.

### Phase 10: Final release gate

1. Run focused tests for all changed areas.
2. Run the full suite after implementation is complete and test-performance work
   has bounded it.
3. Commit and push from this repository.
4. Pull and redeploy in `/Users/tinker/octopus` using `./octopus redeploy --yes`.
5. Verify deployed Registry health and connected bot health.
6. Run final real Safari checks for Registry and Telegram.
7. Confirm working trees are clean in both the source repo and octopus deploy
   checkout.

Acceptance:

- The shipped branch satisfies every acceptance criterion below.
- The deployed octopus checkout runs the same committed branch.
- No known plan item remains open.

## Acceptance Criteria

The plan is complete only when all of the following are true in committed code,
focused tests, final full-suite verification, docs, deployment, and real Safari
QA:

1. Multi-file artifacts always expose zip download.
2. New Auto Protocol runnable artifacts declare a runtime manifest; process- and
   API-backed artifacts cannot be accepted without one.
3. Registry validates and persists runtime state.
4. Bot runtime starts/stops artifact processes through SDK/management contracts.
5. Registry routes UI/API access through stable authenticated URLs.
6. Telegram links use configured public base URLs and clearly label localhost
   links as host-local.
7. Runs UI makes runnable primary artifacts obvious and usable.
8. Runs UI defaults to recent meaningful runs and exposes clear human filters
   without burying Registry/Telegram user runs behind generated/audit mode.
9. Users can improve an existing run from Registry and Telegram through the
   canonical Auto Protocol revise/apply/publish/run lifecycle.
10. Users can start, open, test, check health, inspect logs/events, stop,
   archive, and delete runtime instances according to permissions.
11. Final reviewers exercise runnable artifacts and persist rationale/evidence.
12. Final acceptance is blocked for runnable artifacts without linked start,
   health, and smoke evidence.
13. Review send-back and acceptance reasons are visible in Registry, Telegram,
   and exports.
14. Directory browse and zip download remain available for every multi-file artifact.
15. Tests cover SDK, Registry, Bot runtime, Telegram, UI, routing, lifecycle,
   cleanup, review evidence, and Auto Protocol planner/validation behavior.
16. Full suite has a defined wall-time budget and focused suites support fast
   local iteration.
17. Documentation explains runtime artifacts, links, lifecycle, cleanup, review
   evidence, test tiers, and the Java/Maven risk-engine probe.
18. The risk-engine class of Java/Maven backend plus browser UI runs inside the
   bot container and is reachable through Registry and Telegram URLs.
19. The risk-engine UI submits at least one scenario decision through routed API
   paths and exposes audit/explainability evidence.
20. OpenAPI contract checks fail CI when route behavior and docs drift.
21. Agents receive SDK-backed awareness of protocols, recent runs, primary
   artifacts, runtime outcomes, workspace/tool capabilities, and relevant
   actions in both Registry and Telegram conversation turns.
22. Future bot implementations can implement the awareness behavior through SDK
   interfaces without copying Registry store code or Telegram command handlers.
23. The final deployed `/Users/tinker/octopus` checkout is on the committed
   branch, healthy, and verified in real Safari.

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

## Resolved Implementation Decisions

These decisions govern the remaining execution sequence. They are not deferred
questions.

1. Runtime ownership:
   use the agent that produced the artifact when known; otherwise use the run
   entry agent. Persist the selected bot/agent on the runtime instance so subsequent
   stop, health, logs, archive, delete, and proxy actions do not re-infer
   ownership.
2. Port allocation:
   the supervisor allocates from a configurable bot-local range and never trusts
   a manifest-selected public port. The manifest may declare the placeholder
   variable it expects, but the assigned value comes from the supervisor.
3. Proxy scope:
   standard HTTP UI/API routing is mandatory now. HTML, JS, CSS, images, JSON
   APIs, common HTTP methods, request bodies, redirects, response headers,
   health checks, and API errors must work for the risk-engine probe. Streaming
   HTTP and WebSocket declarations must fail with clear blocked responses
   because they are not supported transports in this plan; they must not produce
   broken links.
4. Runtime timeout:
   use conservative SDK policy defaults and persist resolved timeout values per
   instance. The cleanup policy can tune defaults, but runtime instances must
   always have explicit idle and max-duration limits.
5. Public URL config:
   reuse the existing Registry public URL environment variables for Registry and
   Telegram runtime links. When the resolved base is localhost, label the link as
   host-local and do not imply remote-device reachability.
6. Permissions:
   start and status use the same protocol-run visibility/access path. Stop
   requires access to the run. Archive and delete require mutation rights for
   the run/artifact runtime record.
7. Runtime logs:
   persist event summaries and bounded log tails. Keep full logs in the bot
   workspace while the runtime exists, then clean them according to retention
   policy. Exports include bounded runtime evidence, not unbounded raw logs.
8. Test budget:
   measure current timings first, then set the full-suite wall-time budget in
   team policy before changing CI gates. Focused suites are mandatory for local
   iteration, but the final gate still includes the full suite once bounded.

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
