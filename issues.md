# Issues And Refactoring Plan

This document is the source of truth for removing ambiguous "capability"
language and aligning the current implementation with the product and
architecture decisions.

This is a consolidation pass requested by the product owner. Earlier findings
from the first `issues.md` audit are absorbed here and are no longer maintained
as separate working sections.

## Execution Status

Status after the current implementation pass:

| Area | Status | Evidence |
| --- | --- | --- |
| Vocabulary guardrails | Completed | `tests/test_product_vocabulary_contract.py` enforces no user-facing `Capabilities` product copy, no `ManagementCapability`, no old management bucket errors, and no old transport/admin status fields outside explicit migration/legacy-normalization exceptions. |
| SDK admin protocol naming | Completed | Management support is now concrete `supported_admin_operations`; bucket-style `ManagementCapability` and `capability_not_available` are removed. |
| Agent status naming | Completed | Agent status separates `transport_implementations`, `implemented_sdk_interfaces`, `registry_projection_interfaces`, and `supported_admin_operations`. |
| DB/store schema naming | Completed with migration backfill | New domain columns are used; old `capability` and `_capabilities_json` names only remain in SQL backfill checks for existing deployments. |
| Admin control-plane fields | Completed | `ControlCommand` uses `admin_interface`, `admin_operation`, and `implementation_ref`; routed-work public APIs still use `authority_ref` where the domain concept is agent/task routing authority. |
| Registry projection split | Completed | `registry_capabilities.py` was replaced by `registry_projection_interfaces.py`; `mirror_retry` is not a standalone admin interface. |
| Transport naming | Completed | Transport status uses transport implementations and egress features instead of transport capabilities. |
| Provider guidance summary | Completed | Provider prompt/tool context uses `active_skill_tools_summary` and "Active skill tools". |
| Registry UI product language | Completed in source | UI source now labels the product surface as Skills; legacy `new_capability` selector values are accepted only as input normalization and return `new_skill`. |
| Documentation vocabulary | Completed for touched docs | README, architecture, SDK, registry, protocol, and skills docs use the updated product/architecture vocabulary. |
| Product invariant canary matrix | In progress | Full Python suite and targeted JS syntax checks pass for the current implementation. Deployed Registry UI, Telegram, CLI, routing/delegation, protocol execution, and artifact-access canaries still need to run after this commit is deployed. |
| Live Safari verification | Completed for this refactor | After deploy and `Cmd+Option+R` hard refresh, real Safari shows `Skills` in navigation, loads the Skills catalog, expands Architecture inline, and loads M1 skill instructions. |
| Octopus CLI peer-admin service alignment | Completed | `OctopusAdminService` now owns CLI admin semantics over the existing manager implementation; CLI command methods delegate to that service instead of carrying a parallel operation path. |
| Work lineage and artifact contract | Completed | Task, conversation task cards, and run artifacts now share artifact row/action helpers; unavailable declared outputs render a reason and still allow path copy instead of dead-looking rows or broken actions. |
| Generated/test data hygiene | Completed | Conversations, routed tasks, and protocol runs now carry `source_kind` and `hidden_from_default_views`; default UI calls pass `include_generated=0` so server pagination hides generated/rehearsal/test/protocol-stage noise before client-side defense-in-depth filtering. |
| Performance and responsiveness | Completed for current scope | Added server-side generated filtering, query indexes for default lists, status/default task lists, parent conversation task lookup, protocol-run task lookup, and run default lists. |

Verification completed in this pass:

| Command | Result |
| --- | --- |
| `node --check` on modified Registry UI JavaScript files | Passed |
| `./.venv/bin/python -m pytest tests/test_control_plane_adapters.py tests/test_control_plane_ports.py tests/test_registry_control_processor.py tests/test_registry_mirroring.py tests/test_sdk_composition.py -q` | 50 passed |
| `./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_runtime_process_profile.py tests/test_registry_adapter.py tests/contracts/test_registry_store_contract.py::test_create_routed_task_disabled_routing_skill_raises -q` | 60 passed |
| `./.venv/bin/python -m pytest tests/test_registry_management_protocol.py tests/test_registry_service.py::test_agent_scoped_management_route_reports_missing_admin_operation tests/test_db_postgres.py -q` | 21 passed |
| `./.venv/bin/python -m pytest tests/test_control_plane_integration.py tests/test_agents.py::test_registry_channel_services_resolve_runtime_agent_id_after_enrollment tests/test_execution_finalization.py -q` | 14 passed |
| `./.venv/bin/python -m pytest tests/test_product_vocabulary_contract.py -q` | 4 passed |
| `./.venv/bin/python -m pytest tests/test_protocol_docs.py tests/test_product_vocabulary_contract.py tests/test_registry_ui_contract.py tests/test_registry_management_protocol.py tests/test_registry_service.py::test_agent_scoped_management_route_reports_missing_admin_operation tests/test_db_postgres.py tests/test_control_plane_adapters.py tests/test_control_plane_ports.py tests/test_registry_control_processor.py tests/test_registry_mirroring.py tests/test_sdk_composition.py tests/test_control_plane_integration.py tests/test_execution_finalization.py tests/test_runtime_process_profile.py tests/test_registry_adapter.py -q` | 149 passed |
| `./.venv/bin/python -m pytest -q` | 2217 passed |
| `node --check` on modified Registry UI JavaScript files | Passed after artifact/generated-filter changes |
| `./.venv/bin/python -m pytest tests/test_octopus_cli.py tests/test_registry_ui_contract.py -q` | 52 passed |
| `./.venv/bin/python -m pytest tests/test_registry_service.py -q` | 117 passed |
| `./.venv/bin/python -m pytest tests/test_db_postgres.py -q` | 12 passed |
| `./.venv/bin/python -m pytest -q` | 2220 passed |
| `git push origin feature/protocol` then `git -C /Users/tinker/octopus pull --ff-only origin feature/protocol` | Deployed checkout advanced to `c7fea4f6`. |
| `./octopus redeploy --yes` | Registry, M1, and M2 rebuilt/restarted on current images; M3 failed because Claude auth is not configured. |
| `./octopus status` | Registry running; M1 and M2 connected with healthy execution; M3 enrollment failed due missing Claude auth. |
| Real Safari desktop hard refresh and smoke | Navigation shows `Skills`; Skills catalog renders; Architecture expands inline and loads skill instructions from M1. |

Remaining execution order:

1. Commit and push the current implementation.
2. Pull the pushed commit in `/Users/tinker/octopus`, redeploy Registry/M1/M2, and treat M3 Claude auth as an explicit environment exception until configured.
3. Run the public-path canary matrix against the deployed topology, including Registry UI, Telegram-relevant tests, CLI status/lifecycle smoke, routing/delegation, protocol authoring/execution, and artifact access.
4. Hard-refresh real Safari with `Cmd+Option+R` and visually verify default-list hygiene, task/run artifact actions, and core navigation.

## Problem Statement

The current codebase uses `capability` to mean several unrelated things:

| Current Use | Actual Meaning |
| --- | --- |
| User-facing `Capabilities` page | Skills catalog and skill lifecycle |
| `ManagementCapability` | Buckets of management operations |
| `management_capabilities` | Runtime-implemented management behavior |
| `channel_capabilities` | Transport implementations/types |
| `TransportCapabilities` | Egress behavior/features |
| `ControlCommand.capability` | Admin/control interface being invoked |
| `registry_authority_capabilities()` | Admin interface coverage for configured implementations |
| `capability_summary` | Active skill tool/script prompt summary |

This causes product and engineering confusion:

- Users see `Capabilities` when the product concept is `Skills`.
- Engineers see `capability` and cannot tell whether it means skill,
  transport, management, control plane, SDK interface coverage, or registry
  projection.
- Registry becomes over-central in naming even when Octopus CLI is also
  supposed to be a full admin/operational implementation.
- Management support is modeled as vague capability buckets instead of concrete
  supported management operations.
- Storage details such as `_json` leak into names where the domain concept
  should be clear without naming the serialization format.

The fix is not a mechanical rename. The fix is to replace vague nouns with the
actual product and architecture constructs.

## Product And Architecture Decisions

### Product Constructs

These are valid product nouns:

| Noun | Meaning |
| --- | --- |
| Agent | Runtime process that implements SDK interfaces and performs work. |
| Skill | User-facing work ability that can be installed, activated, authored, or selected. |
| Routing skill | Skill projection used for delegation/routing between agents. |
| Protocol | Reusable workflow definition. |
| Run | Execution of a protocol. |
| Delegation | Agent-to-agent routed work. |
| Artifact | File/document/output referenced or produced by work. |
| Guidance | Provider baseline instruction/policy. |
| Conversation | Human/agent collaboration thread. |
| Pending human action | Review/approval/intervention item that needs a person. |

Do not introduce a generic product noun such as `capability`, `ability`,
`surface`, or `hub`.

### Architecture Constructs

These are valid architecture nouns:

| Noun | Meaning |
| --- | --- |
| SDK interface | Contract provided by the SDK. |
| Implementation | Concrete binding of an SDK interface. |
| Admin interface | SDK/admin contract used by operational clients such as Registry UI/API and Octopus CLI. |
| Admin operation | Concrete operation exposed through an admin interface. |
| Transport implementation | Concrete transport binding such as Telegram or Registry delivery. |
| Registry projection | Runtime state mirrored into Registry for UI/API visibility. |
| Provider implementation | Concrete provider binding such as Claude or Codex. |
| Store implementation | Concrete persistence binding such as Postgres. |

Registry is one implementation/client surface. Octopus CLI is also an
admin/operational implementation. The naming must not make Registry the owner
of shared admin semantics.

### Interface Availability Rule

The SDK interface is the contract. A runtime may or may not implement it. An
implementation may be healthy or unhealthy.

Do not say "the interface is unavailable" when the accurate statement is one of
these:

- The runtime does not implement this admin interface.
- The runtime implements this admin interface but not this admin operation.
- The runtime implements this admin operation but is currently unhealthy.
- The runtime is disconnected.
- The actor is not allowed to invoke this operation.

### Naming And Casing Rules

| Layer | Rule |
| --- | --- |
| Product UI text | Use normal English product nouns: Skills, Runs, Delegations, Artifacts. |
| Docs headings | Title Case is fine for human-readable concepts. |
| Python classes/types | `PascalCase`. |
| Python functions/fields | `snake_case`. |
| API fields | `snake_case`, matching current API style. |
| DB columns | `snake_case`; do not include `_json` when type already records JSONB. |
| JS local variables | Existing JS style is acceptable; API field names stay as API returns them. |

Do not append `_json` to domain/API names. If a store adapter needs a raw local
value, use `_raw` only inside the persistence boundary.

## Target Architecture

### Runtime Composition

An agent runtime is composed from SDK interfaces and concrete implementations:

| SDK Interface | Example Implementations |
| --- | --- |
| Transport interface | Telegram transport, Registry delivery transport |
| Registry projection interface | Registry participant implementation |
| Admin interface | Runtime admin implementation used by Registry UI/API and Octopus CLI |
| Provider interface | Claude provider, Codex provider |
| Store interface | Postgres stores |
| Skill workflow interface | Built-in/custom/store skill workflows |
| Protocol interface | Protocol authoring, run observation, run invocation |

### Admin Clients

Registry UI/API and Octopus CLI are peer admin clients.

| Admin Client | Role |
| --- | --- |
| Registry UI/API | Browser and HTTP admin/product surface over projected runtime state and admin operations. |
| Octopus CLI | Local operational/admin implementation for deployment, status, logs, shell, doctor, and future product/admin operations. |
| Telegram | User transport, not the primary admin client, but may invoke shared management/admin operations where exposed. |

Registry-specific projection remains Registry-specific. Shared admin semantics
must live in SDK/admin code, not Registry-only code.

### Agent Status Shape

Agent status must separate these fields:

| Field | Meaning |
| --- | --- |
| `implemented_sdk_interfaces` | SDK contracts implemented by this runtime. |
| `transport_implementations` | Concrete transports reported by runtime. |
| `registry_projection_interfaces` | Registry projection areas implemented by runtime. |
| `supported_admin_operations` | Concrete admin operations implemented by runtime. |
| `skills` | Skills available on this agent. |
| `routing_skills` | Skills advertised for delegation/routing. |
| `runtime_state` | Connected, degraded, faulted, capacity, heartbeat. |

The user-facing UI should primarily show skills, routing skills, work, and
health. SDK interface details and concrete implementation details belong in
operator diagnostics.

## Final Name Map

### Management And Admin Protocol

| Current | Final |
| --- | --- |
| `ManagementCapability` | Delete. No replacement type. |
| `MANAGEMENT_OPERATION_CAPABILITIES` | Delete. Operation grouping is not needed for product semantics. |
| `required_management_capability()` | Delete. |
| `management_capability_supported()` | Delete. |
| `management_capabilities` | `supported_admin_operations` |
| `management_capabilities_resolver` | `supported_admin_operations_resolver` |
| `capability_not_available` | Replace with specific admin errors. |

Concrete admin errors:

| Error | Use |
| --- | --- |
| `agent_not_connected` | Agent is disconnected. |
| `admin_interface_not_implemented` | Runtime does not implement the admin interface. |
| `admin_operation_not_implemented` | Runtime implements admin interface but not operation. |
| `admin_operation_unavailable` | Operation exists but is temporarily unhealthy/unavailable. |
| `admin_operation_forbidden` | Actor lacks permission. |
| `admin_request_invalid` | Request payload is invalid. |
| `admin_request_timeout` | Request timed out. |

### Control Plane And Admin Work

The existing control plane should be renamed around admin interfaces and admin
operations, not around registry-specific projection unless the command is truly
Registry-only.

| Current | Final |
| --- | --- |
| `ControlCommand` | Keep initially, then evaluate `AdminCommand` after the first refactor compiles. |
| `ControlCommand.capability` | `admin_interface` |
| `ControlCommand.operation` | `admin_operation` |
| `authority_ref` when it is a target implementation | `implementation_ref` |
| `authority_capabilities()` | `implemented_admin_interfaces()` |
| `allowed_pairs` | `allowed_admin_targets` |
| `_processor_by_pair` | `_processor_by_admin_target` |

Do not use `control_command_kind`.

### Registry Projection

Use Registry-specific names only for Registry-specific projection.

| Current | Final |
| --- | --- |
| `registry_capabilities.py` | `registry_projection_interfaces.py` or `admin_interfaces.py`, depending on final ownership after code split. |
| `registry_authority_ref()` | `registry_implementation_ref()` |
| `registry_authority_capabilities()` | `registry_projection_interfaces_by_implementation_ref()` only if projection-specific. |
| `mirror_retry` | Remove as separate interface; retry belongs to projection behavior. |

If the function is used for shared admin/control processing, it must not be
Registry-specific. Use:

```text
implemented_admin_interfaces_by_implementation_ref()
```

If the function is only converting configured Registry connections into
Registry projection coverage, use:

```text
registry_projection_interfaces_by_implementation_ref()
```

The code must be inspected at implementation time and split accordingly rather
than forcing one name onto both roles.

### Transport

| Current | Final |
| --- | --- |
| `TransportCapabilities` | `TransportEgressFeatures` |
| `TransportEgress.capabilities` | `TransportEgress.egress_features` |
| `contributes_transport_capability` | `report_in_agent_status` |
| `active_transport_types()` | `reported_transport_implementations()` |
| `channel_capabilities` | `transport_implementations` |
| `channel_capabilities_resolver` | `transport_implementations_resolver` |
| `channel_name` inside transport feature record | `transport_implementation` |

### Provider Guidance

| Current | Final |
| --- | --- |
| `capability_summary` | `active_skill_tools_summary` |
| "Active skill tool surface" copy | "Active skill tools" |

### Product UI

| Current | Final |
| --- | --- |
| `Capabilities` navigation | `Skills` |
| `capability hub` | `skill catalog` |
| `New capability` | `New skill` |
| `Existing capability` | `Existing skill` |
| `Required capability` | `Required skill` |
| `Needed capability` | `Needed skill` |
| `Conversation capabilities` | `Conversation skills` or `Active skills` |
| `Activate Capability` | `Activate skill` |
| `new_capability` | `new_skill` |
| `capabilityNeed` | `neededSkill` |

## Current Evidence Inventory

The following files currently contain high-priority naming or architecture
issues:

| Area | Files |
| --- | --- |
| SDK management | `octopus_sdk/registry/management.py`, `octopus_sdk/registry/management_executor.py` |
| Runtime composition | `octopus_sdk/composition.py`, `octopus_sdk/bot_runtime.py` |
| Registry management adapter | `octopus_registry/management_client.py`, `octopus_registry/ingress.py` |
| Agent registry models | `octopus_sdk/registry/models.py`, `app/runtime/registry_participant.py` |
| Registry store | `octopus_registry/store_shared/agents.py`, `octopus_registry/store_base.py`, `octopus_registry/store_postgres.py` |
| DB schema | `app/db/init.sql`, `app/db/postgres_doctor.py` |
| Control plane | `app/control_plane/models.py`, `app/control_plane/directory.py`, `app/control_plane/processor_base.py`, `app/control_plane/processor_runner.py`, `app/control_plane/postgres_impl.py`, `app/control_plane/adapters/*` |
| Registry projection helpers | `app/agents/registry_capabilities.py`, `app/agents/registry_control_processor.py` |
| Transport | `octopus_sdk/transport.py`, `octopus_sdk/transport_dispatcher.py`, `app/channels/telegram/*`, `app/channels/registry/*` |
| Provider guidance | `octopus_sdk/workflows/provider_guidance.py`, `octopus_sdk/provider_guidance_service.py`, `app/providers/claude.py`, `app/providers/codex.py` |
| Registry UI | `octopus_registry/ui/index.html`, `octopus_registry/ui/js/components/*`, `octopus_registry/ui/js/helpers/*` |
| Octopus CLI | `app/octopus_cli/*` |
| Docs | `README.md`, `docs/ARCHITECTURE.md`, `docs/skills-model.md`, `docs/skills-guide.md`, `docs/sdk-bot-development.md`, `docs/registry-user-guide.md`, `docs/author-protocol-guide.md`, `docs/protocol_assignment_audit.md`, `docs/telegram-user-guide.md` |
| Tests | `tests/test_registry_service.py`, `tests/test_registry_management_protocol.py`, `tests/test_channel_dispatcher.py`, `tests/test_runtime_dispatch_boundary.py`, `tests/test_control_plane_*`, `tests/test_sdk_composition.py`, `tests/test_skills.py`, Playwright UI specs |

## Implementation Plan

### Phase 0: Guardrails And Baseline Inventory

Goal:

Make the intended vocabulary and boundary rules executable before the rename
starts.

Implementation:

1. Add a vocabulary contract test for user-facing UI and docs.
2. Add an SDK boundary contract test.
3. Add an agent status shape contract test.
4. Add an admin error-code contract test.
5. Add a temporary inventory script/test that lists remaining forbidden terms
   by category.

Allowed temporary exceptions:

| Exception | Reason |
| --- | --- |
| `issues.md` | This file must mention old names. |
| Generated OpenAPI before regeneration | Will be regenerated after API changes. |
| Migration/backfill comments | Temporary during schema refactor only. |
| Third-party or historical package names | Must be reviewed case by case. |

Forbidden by default:

| Pattern | Reason |
| --- | --- |
| UI text `Capabilities` for skills | Product noun is Skills. |
| `ManagementCapability` | Wrong model. |
| `management_capabilities` | Wrong model. |
| `channel_capabilities` | Wrong model. |
| `capability_not_available` | Wrong error. |
| `capability_summary` | Wrong provider guidance field. |
| New generic terms like `ability`, `hub`, `surface`, `route`, `kind` as replacements | Recreates ambiguity. |

Verification:

- New guardrail tests fail before implementation.
- Inventory output is checked into test snapshots or printed as actionable
  failures.

### Phase 0A: Product Invariant Canary Matrix

Goal:

Protect the currently working product while refactoring. The safety net must not
fixate on any single recent failure or example. It must cover the full product
surface as a matrix of invariants that are exercised through real public paths
and deployed topology.

Principles:

- Do not treat one recent bug as the majority scope.
- Do not prove behavior by directly populating the database.
- Do not rely only on unit tests for cross-runtime product behavior.
- Do inspect the database after a canary run when diagnosing failures.
- Do run canaries against the same Docker/deployed local topology used by real
  development and demos.
- Do use the real configured agents, currently m1, m2, m3, and any explicitly
  configured rehearsal/runtime agent.
- Do run the relevant canary subset after each implementation phase.
- Do run the full matrix before push/deploy and after deploy with Safari hard
  refresh for UI-facing changes.

Canary matrix:

| Product Invariant | Public Path | Minimum Assertions |
| --- | --- | --- |
| Agent registration | Start/redeploy stack; Registry API/UI agent list | m1/m2/m3 register, heartbeat, show connected/degraded truthfully, stale/generated agents hidden or marked. |
| Runtime health | Registry UI/API and `./octopus status`/`doctor` | Provider health, execution fault state, capacity, heartbeat, and connectivity match runtime reality. |
| Skill catalog | Registry Skills UI/API and Telegram `/skills list` | Core skills visible, generated/test noise hidden by default, skill detail readable, no `Capabilities` product copy. |
| Conversation creation | Registry UI new conversation and Telegram `/new` | New conversation created, not prefilled with stale demo data, appears in Registry projection. |
| Conversation execution | Registry UI and Telegram message path | Message creates work, work is claimed, provider executes, response appears, events are projected. |
| Conversation skill activation | Registry conversation skills panel and Telegram `/skills add/remove/setup` | Activate/deactivate persists, setup prompts work, active skills affect execution context. |
| Agent-directed work | Registry UI/API or Telegram direct target syntax | User can target a specific agent; selected agent receives and completes work. |
| Skill-routed work | Registry UI/API or Telegram skill target syntax | Routing by skill resolves a matching agent, records the selected agent, and completes. |
| Delegation | Agent-originated delegation through public conversation path | Origin agent delegates, target agent receives/claims/completes, result returns or is inspectable, Registry shows linked delegation. |
| Protocol authoring | Registry Protocols UI only | Create protocol, add stage, remove stage, edit stage, save draft, publish without losing entered data. |
| Protocol assignment | Registry Protocols UI only | No assignment, skill, agent, skill plus preferred agent, and needed new skill all persist and render correctly. |
| Protocol execution | Registry UI/API and Telegram `/protocol start` where exposed | Published protocol starts, stages progress, assignments resolve, terminal state is correct. |
| Run inspection | Registry Runs UI | Overview, stages, artifacts, audit/timeline, actions, and linked work are understandable and not all expanded by default. |
| Artifact access | Registry UI/API and Telegram artifact links | Declared/produced/unavailable states correct; preview/open/download/copy path work or show disabled explanation. |
| Guidance lifecycle | Registry Guidance UI/API and Telegram `/guidance` | Preview/edit/submit/publish flows work and published guidance affects provider prompt composition. |
| Registry projection | Telegram-originated conversation/work and Registry UI | Telegram messages, events, delegated work, runs, artifacts, and state appear in Registry without direct DB writes. |
| Octopus CLI admin | `./octopus status doctor logs shell redeploy` | CLI remains functional and reports the same runtime truth as Registry where concepts overlap. |
| Operations surfaces | Dashboard/routing/usage/linked pending human actions | Operational data is useful, non-empty when expected, and does not create duplicate product surfaces. |
| Persistence/restart | Restart/redeploy then inspect UI/API/CLI | Conversations, runs, skills, artifacts, registrations, and work state survive expected restart boundaries. |
| Performance/responsiveness | Registry UI desktop and narrow Safari | Key surfaces first-paint without loading everything, pagination works, no broken scrolling or cache-stale asset behavior. |

Canary execution rules:

1. Establish a known-good baseline before Phase 1 begins.
2. Store the canary commands, UI steps, and expected assertions in the repo.
3. Capture output artifacts/screenshots for UI-facing canaries.
4. Run the relevant subset after each phase.
5. Run the full matrix before deploy/push.
6. Run the full matrix after deploy when the phase touched API, UI, routing,
   transport, CLI, persistence, or runtime composition.
7. If any canary fails, stop the refactor phase and either fix the regression or
   explicitly record the blocker in this plan before continuing.

Required baseline artifacts:

| Artifact | Purpose |
| --- | --- |
| Canary command list | Makes the test repeatable by a human and by automation. |
| UI step document | Prevents hidden direct-DB setup from masquerading as product verification. |
| Expected event/task/run shape fixtures | Detects silent routing/projection regressions. |
| Screenshot set | Catches visual density, expansion, action visibility, and layout regressions. |
| Deployment/topology snapshot | Confirms tests used real m1/m2/m3 deployed topology. |

Definition of a valid canary:

- It starts from a public UI, Telegram, CLI, or SDK/API entry point that matches
  real product use.
- It verifies the user-visible outcome and the projected system state.
- It does not directly create the state it is supposed to prove.
- It fails loudly on missing UI actions, stale data, broken routing, missing
  artifacts, ambiguous terminal states, or mismatched agent identities.

### Phase 1: Refactor SDK Admin Protocol

Goal:

Move shared admin/management semantics out of Registry naming and express
support as concrete admin operations.

Implementation:

1. Create neutral SDK admin package.
2. Move typed management request/result models from `octopus_sdk.registry.management`.
3. Move bot-side management executor from `octopus_sdk.registry.management_executor`.
4. Keep existing `ManagementOperation` values initially if the name is still
   accurate in code; otherwise rename to `AdminOperation` in the same pass.
5. Delete `ManagementCapability`.
6. Delete operation-to-capability bucket mapping.
7. Replace `WorkflowComposition.management_capabilities` with
   `supported_admin_operations`.
8. Build `supported_admin_operations` from wired workflow implementations.
9. Update Registry ingress and management client imports to the neutral package.
10. Update tests to assert concrete operations, not buckets.

Concrete operation coverage examples:

```text
list_catalog_skills
search_catalog_skills
catalog_skill_detail
catalog_skill_lifecycle_detail
edit_catalog_skill_draft
export_catalog_skill_package
import_catalog_skill_package
submit_catalog_skill
approve_catalog_skill
reject_catalog_skill
publish_catalog_skill
archive_catalog_skill
install_catalog_skill
uninstall_catalog_skill
update_catalog_skill
diff_catalog_skill
conversation_skill_state
activate_conversation_skill
deactivate_conversation_skill
clear_conversation_skills
submit_conversation_skill_credential
conversation_settings_state
set_conversation_setting
reset_conversation
reset_execution_fault
preview_provider_guidance
provider_guidance_detail
edit_provider_guidance_draft
submit_provider_guidance
approve_provider_guidance
reject_provider_guidance
publish_provider_guidance
archive_provider_guidance
```

Important constraint:

Do not introduce operation groups as a renamed capability layer. If grouping is
needed for UI filtering later, derive it locally in UI from concrete operations
without making it a domain/API contract.

Verification:

- SDK admin protocol tests pass.
- Registry management protocol tests pass with concrete operation support.
- No code imports shared admin models from `octopus_sdk.registry.management`.

### Phase 2: Refactor Agent Status And Registration

Goal:

Make agent status tell the truth about interfaces, implementations, skills,
routing skills, admin operations, and health.

Implementation:

1. Update SDK registry agent models.
2. Update agent registration payloads.
3. Update heartbeat/status records.
4. Update runtime participant code.
5. Update Registry store read/write paths.
6. Update generated OpenAPI after API shape stabilizes.

Target agent record:

```text
agent_id
agent_token
bot_key
display_name
slug
role
registry_scope
skills
routing_skills
tags
description
provider
mode
connectivity_state
current_capacity
max_capacity
transport_implementations
implemented_sdk_interfaces
registry_projection_interfaces
supported_admin_operations
runtime_health
trust_tier
soft_deleted_at
created_at
updated_at
last_heartbeat_at
```

Notes:

- `skills` are product-facing available skills.
- `routing_skills` are product-facing routing/delegation skills.
- `transport_implementations` are concrete implementation identifiers.
- `implemented_sdk_interfaces` are operator/developer diagnostics.
- `registry_projection_interfaces` are Registry projection-specific.
- `supported_admin_operations` are concrete operations.

Verification:

- Agent registration tests assert new fields.
- Agent status API tests assert old fields are gone.
- UI tests consume new fields.
- Telegram and Registry delivery still register correctly.

### Phase 3: Refactor Persistence Schema

Goal:

Remove ambiguous storage names and avoid storage-format suffixes in domain
columns.

Implementation:

1. Update `app/db/init.sql`.
2. Update `app/db/postgres_doctor.py`.
3. Update store adapters.
4. Update tests.
5. Provide one-time migration/backfill if this is applied to an existing
   deployed database.

Target column changes:

| Table | Current | Final |
| --- | --- | --- |
| `agent_registry.agents` | `channel_capabilities_json` | `transport_implementations` |
| `agent_registry.agents` | `management_capabilities_json` | `supported_admin_operations` |
| `agent_registry.agents` | add | `implemented_sdk_interfaces` |
| `agent_registry.agents` | add | `registry_projection_interfaces` |
| `agent_registry.management_requests` | `capability` | remove |
| `bot_runtime.control_plane_commands` | `capability` | `admin_interface` |
| `bot_runtime.control_plane_commands` | `operation` | `admin_operation` |
| `bot_runtime.control_plane_commands` | `authority_ref` | `implementation_ref` |

Index changes:

| Current | Final |
| --- | --- |
| `idx_cp_idempotency(capability, operation, authority_ref, idempotency_key)` | `idx_admin_idempotency(admin_interface, admin_operation, implementation_ref, idempotency_key)` |

Schema rule:

Use `JSONB` where arrays remain practical, but do not use `_json` in the column
name. The type already describes storage.

Verification:

- Postgres doctor validates new columns and indexes.
- Store contract tests pass.
- No code reads old columns outside a one-time migration.

### Phase 4: Refactor Admin Control Plane

Goal:

Make the control plane a generic admin command mechanism that can be used by
Registry UI/API and Octopus CLI, not a Registry-only capability mapper.

Implementation:

1. Rename command fields.
2. Rename directory/processor vocabulary.
3. Update control-plane adapters.
4. Update Postgres command store.
5. Update tests.
6. Keep command lifecycle/state-machine behavior unchanged.

Target model:

```python
class ControlCommand(BaseModel):
    command_id: str
    admin_interface: str
    admin_operation: str
    implementation_ref: str
    payload: dict[str, object]
    state: str
    priority: int
    correlation_id: str
    idempotency_key: str
```

The class can remain `ControlCommand` during the first pass to reduce blast
radius. Rename to `AdminCommand` only after all tests are green and the concept
is proven.

Target interfaces currently represented:

| Admin Interface | Existing Source |
| --- | --- |
| `conversation_projection` | Registry conversation/event mirroring |
| `work_delegation` | Routed task submission/update/result |
| `agent_directory` | Agent discovery and target resolution |
| `health_publication` | Heartbeat/health projection |
| `registry_inspection` | Registry inspection/diagnostics |

Important:

- These are admin interfaces, not capabilities.
- Registry projection interfaces are a subset when the target is Registry.
- Octopus CLI should use the same admin service layer where it performs admin
  operations instead of creating parallel command logic.

Verification:

- Control plane model tests pass.
- Control plane processor runner tests pass.
- Integration tests prove command dispatch by `(implementation_ref,
  admin_interface)`.
- Octopus CLI can be wired to the same admin service layer in later phases.

### Phase 5: Split Registry Projection From Shared Admin

Goal:

Use Registry-specific names only for Registry projection and keep shared admin
semantics neutral.

Implementation:

1. Inspect `app/agents/registry_capabilities.py` usage.
2. If the helper is only Registry projection, rename it to
   `registry_projection_interfaces.py`.
3. If the helper feeds shared admin dispatch, move the shared part to
   `app/admin/interfaces.py`.
4. Keep Registry-specific implementation references clearly named.
5. Remove `mirror_retry` as a separate interface.

Target functions:

If shared:

```text
implemented_admin_interfaces_by_implementation_ref(config)
```

If Registry projection-specific:

```text
registry_projection_interfaces_by_implementation_ref(registries)
registry_implementation_ref(registry_id)
registry_id_from_implementation_ref(implementation_ref)
```

Registry projection interfaces:

```text
conversation_projection
event_projection
work_projection
health_projection
agent_directory_projection
registry_inspection
```

Retry behavior:

- Projection retry is part of projection command lifecycle.
- It must not appear as its own advertised interface.

Verification:

- Registry control processor tests pass.
- Mirroring tests pass.
- No `registry_authority_capabilities` remains.
- No `mirror_retry` admin interface remains.

### Phase 6: Refactor Transport Naming

Goal:

Make transport code describe concrete implementations and egress features.

Implementation:

1. Rename `TransportCapabilities` to `TransportEgressFeatures`.
2. Rename `TransportEgress.capabilities` to `egress_features`.
3. Rename descriptor flag `contributes_transport_capability` to
   `report_in_agent_status`.
4. Rename dispatcher method `active_transport_types()` to
   `reported_transport_implementations()`.
5. Rename resolver arguments in Registry delivery transport.
6. Update tests.

Target model:

```python
class TransportDescriptor:
    transport_type: str
    display_name: str
    supports_multiple: bool
    inbound_model: str
    report_in_agent_status: bool = True

class TransportEgressFeatures:
    can_edit_message: bool
    can_answer_action: bool
    can_send_photo: bool
    can_send_document: bool
    can_render_timeline: bool
    can_present_actions: bool
    can_share_conversation: bool
    transport_implementation: str
```

Verification:

- Transport dispatcher tests pass.
- Telegram egress tests pass.
- Registry delivery transport tests pass.
- Agent registration reports expected transport implementations.

### Phase 7: Refactor Provider Guidance Summary

Goal:

Rename the active-skill prompt/tool summary without inventing a new noun.

Implementation:

1. Rename `capability_summary` to `active_skill_tools_summary`.
2. Update provider guidance workflow models.
3. Update Claude/Codex provider prompt assembly.
4. Update tests and fixtures.
5. Update generated OpenAPI after API changes.

Target copy:

```text
Active skill tools
```

Not:

```text
Active skill tool surface
```

Verification:

- Provider tests pass.
- Skill prompt composition tests pass.
- No `capability_summary` remains outside this plan or migration notes.

### Phase 8: Refactor Registry UI Product Language

Goal:

Remove product-facing `Capabilities` language and align UI with Skills,
Routing Skills, Admin Diagnostics, and Registry Projection.

Implementation:

1. Rename navigation Build item from `Capabilities` to `Skills`.
2. Rename skill catalog page text.
3. Rename conversation detail skills panel.
4. Rename agent detail skill summary.
5. Rename protocol assignment UI states.
6. Move selector diagnostics to operator/diagnostic framing.
7. Update UI helpers and CSS class names only where necessary for clarity.

UI surfaces:

| Surface | Required Result |
| --- | --- |
| Skills page | Skill catalog, available skills, lifecycle, install/create/import/export. |
| Conversation detail | Active skills, add/remove/setup skills, settings, protocols. |
| Agent detail | Identity, health, primary work actions, skills, routing skills, recent work, diagnostics. |
| Protocol editor | Assignment states: none, skill, agent, skill with preferred agent, needed new skill. |
| Runs | Run lineage, artifacts, stages, audit, actions in context. |

Protocol assignment states:

| State | Meaning |
| --- | --- |
| `none` | Stage can be drafted without assignment. |
| `skill` | Stage routes by skill. |
| `agent` | Stage pins a specific agent. |
| `skill_preferred_agent` | Stage routes by skill and prefers one matching agent. |
| `new_skill` | Stage documents a needed skill that is not available yet. |

Verification:

- Playwright protocol authoring tests pass.
- UI vocabulary scan passes.
- Real Safari desktop and narrow smoke pass after deploy and hard refresh.

### Phase 9: Integrate Octopus CLI As Peer Admin Implementation

Goal:

Stop treating Registry as the only admin/operational surface.

Implementation:

1. Identify CLI commands that are already admin operations:
   `status`, `start`, `stop`, `restart`, `redeploy`, `connect`,
   `disconnect`, `logs`, `shell`, `doctor`, `clean`.
2. Define an admin service layer used by CLI command handlers.
3. Keep CLI presentation in `app/octopus_cli`.
4. Keep Docker/process execution implementation behind admin service interfaces.
5. Do not duplicate Registry UI behavior in CLI.
6. Future product/admin CLI commands must call SDK/admin operations, not direct
   Registry UI helper code.

Initial CLI admin interfaces:

| Admin Interface | Operations |
| --- | --- |
| `deployment_admin` | start, stop, restart, redeploy |
| `runtime_status_admin` | status, doctor |
| `registry_connection_admin` | connect, disconnect |
| `log_access_admin` | logs |
| `shell_access_admin` | shell |

These names are for CLI/local admin implementation, not product UI text.

Verification:

- Existing CLI tests pass.
- CLI behavior remains unchanged for current commands.
- New tests prove CLI admin service does not import Registry UI code.

### Phase 10: Rebuild Work Lineage And Artifact Contract

Goal:

Make work concepts human-readable and connected.

Implementation:

1. Define one lineage projection for conversations, delegations, protocol runs,
   stage tasks, events, and artifacts.
2. Keep routed tasks as backing model.
3. Show standalone routed work as `Delegations`.
4. Show protocol stage tasks inside run/stage lineage by default.
5. Keep direct task links valid.
6. Use one artifact row/action primitive everywhere.

Artifact row contract:

| Field/Action | Requirement |
| --- | --- |
| Name | Always shown. |
| Artifact kind | Shown when known. |
| Declared/produced state | Always shown. |
| Exists/unavailable state | Always shown. |
| Workspace path | Shown when known. |
| Preview | Enabled when renderable and available. |
| Open/download | Enabled when content is available. |
| Copy path | Enabled when path is known. |
| Disabled explanation | Required when action is not available. |

Verification:

- Conversation to delegation to artifact flow passes.
- Protocol run to stage task to artifact flow passes.
- Telegram artifact link flow passes.
- No surface shows artifact names without artifact actions or unavailable reason.

### Phase 11: Generated/Test/Rehearsal Data Hygiene

Goal:

Keep normal human surfaces clean without relying on name heuristics.

Implementation:

1. Add explicit source/kind flags where generated records are created.
2. Apply server-side default filters.
3. Add Operations filters for generated/rehearsal/test records.
4. Remove name-based hiding as the primary behavior.

Record flags:

| Field | Meaning |
| --- | --- |
| `source_kind` | human, generated, imported, rehearsal, test |
| `created_by_run_id` | Run that generated the record, if applicable. |
| `hidden_from_default_views` | Derived or policy field, not the only source of truth. |

Verification:

- Mixed real/generated data UI tests pass.
- Skill catalog does not show generated protocol-composer noise by default.
- Operations can still find generated/rehearsal/test records.

### Phase 12: Performance And Responsiveness

Goal:

Make large lists fast through query contracts and progressive loading, not blind
indexing.

Implementation:

1. Add or complete server-side pagination for protocols, runs, conversations,
   delegations, and skills.
2. Add server-side filters for default/operations views.
3. Lazy-load heavy details.
4. Measure query plans for slow endpoints.
5. Add targeted indexes only after query evidence.

Initial endpoints to audit:

| Surface | Need |
| --- | --- |
| Protocols | Paginated list, template filter, lifecycle filter. |
| Runs | Paginated list, status filter, rehearsal/generated filter. |
| Conversations | Paginated list, type/source filter, linked work counts. |
| Delegations | Paginated standalone delegated work. |
| Skills | Search/page catalog, hide generated/test by default. |

Verification:

- First paint timing captured for key surfaces.
- Real Safari desktop and narrow layouts remain stable.
- Query plans justify any new index.

### Phase 13: Documentation Rewrite

Goal:

Make docs match implemented product and architecture.

Implementation:

1. Rewrite README vocabulary and navigation.
2. Rewrite architecture sections around SDK interfaces, implementations,
   projection, admin clients, skills, routing skills.
3. Rewrite skills model and skills guide.
4. Rewrite SDK bot development guide.
5. Rewrite Registry user guide.
6. Rewrite Telegram user guide.
7. Rewrite protocol assignment audit.
8. Regenerate OpenAPI docs after API changes.

Required doc statements:

- Skills are the product work ability noun.
- Routing skills are a derived projection for delegation/routing.
- Registry UI/API and Octopus CLI are peer admin/operational clients.
- Registry projection mirrors runtime state; it does not own agent behavior.
- Management/admin support is concrete supported admin operations.
- Transports are concrete implementations of SDK transport interfaces.

Verification:

- Docs tests pass.
- Static vocabulary scan passes.
- Customer clone/setup/demo path remains accurate.

## Issue Coverage Map

| Prior Finding | Covered By |
| --- | --- |
| N-001 product capability leak | Phases 0, 8, 13 |
| N-002 ManagementCapability | Phases 1, 2, 3 |
| N-003 registry-named management | Phases 1, 9 |
| N-004 interface vs implementation availability | Phases 1, 2 |
| N-005 capability_summary | Phase 7 |
| N-006 control-plane capability | Phase 4 |
| N-007 mirror_retry | Phase 5 |
| N-008 transport capabilities | Phase 6 |
| N-009 agent status fields | Phases 2, 3 |
| N-010 protocol assignment language | Phase 8 |
| N-011 selector internals | Phase 8 |
| N-012 capability hub | Phase 8 |
| N-013 conversation capabilities | Phase 8 |
| N-014 agent detail density | Phase 8 |
| N-015 tasks/runs lineage | Phase 10 |
| N-016 approvals product home | Phase 10 |
| N-017 artifact action contract | Phase 10 |
| N-018 templates/galleries | Phase 8, Phase 13 |
| N-019 generated/test pollution | Phase 11 |
| N-020 stale docs | Phase 13 |
| N-021 performance | Phase 12 |
| N-022 CLI not peer product/admin client | Phase 9 |
| N-023 Telegram parity | Phases 1, 8, 10 |
| N-024 RegistryAuthority naming | Phases 1, 5, 9 |
| N-025 generic operation fields | Phases 1, 4 |
| N-026 test guardrails | Phase 0 and Phase 0A |

## Execution Order

The work should be executed in this order:

1. Phase 0 guardrails and inventory.
2. Phase 0A product invariant canary matrix.
3. Phase 1 SDK admin protocol.
4. Phase 2 agent status/API shape.
5. Phase 3 DB/store schema.
6. Phase 4 admin control plane.
7. Phase 5 Registry projection split.
8. Phase 6 transport naming.
9. Phase 7 provider guidance summary.
10. Phase 8 Registry UI product language.
11. Phase 9 Octopus CLI admin service alignment.
12. Phase 10 work lineage and artifact contract.
13. Phase 11 generated/test data hygiene.
14. Phase 12 performance and responsiveness.
15. Phase 13 docs rewrite.

Do not skip guardrails. Do not skip product invariant canaries. Do not rename UI
only. Do not leave old and new domain fields active as parallel paths.

## Definition Of Done

This refactor is done only when all of the following are true:

- Product UI does not use `Capabilities` for skills.
- Docs do not describe skills and capabilities as the same product concept.
- `ManagementCapability` no longer exists.
- `management_capabilities` no longer exists in domain/API models.
- `channel_capabilities` no longer exists in domain/API models.
- `capability_not_available` no longer exists as an error code.
- `capability_summary` no longer exists as a provider guidance field.
- Agent status separates SDK interfaces, transport implementations, Registry
  projection interfaces, supported admin operations, skills, routing skills,
  and runtime state.
- Registry UI/API and Octopus CLI are documented as peer admin/operational
  clients over shared admin interfaces.
- Telegram remains skill-first and does not gain a parallel management path.
- Protocol assignment supports no assignment, skill, agent, skill with preferred
  agent, and needed new skill.
- Selector internals are not shown in standard authoring.
- Work lineage connects conversations, delegations, runs, stage tasks, events,
  and artifacts.
- Every artifact reference uses the shared artifact row/action contract.
- Generated/rehearsal/test records do not dominate default human surfaces.
- The product invariant canary matrix has a known-good baseline before the
  refactor and passes after every relevant phase.
- Canary execution uses public UI, Telegram, CLI, SDK/API, or deployed runtime
  entry points rather than direct database setup as proof.
- Real Safari desktop and narrow audits pass after deploy and hard refresh.
- Unit, API, UI, Telegram, CLI, docs, and schema tests pass.
