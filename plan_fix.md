**Protocol Assignment Simplification Plan**

This plan replaces the earlier canvas/mobile-only cleanup scope. The current blocking problem is not primarily visual polish. It is that protocol authoring still splits one user job across two concepts:

- the **step** is where authors think about work
- the **participant** is where assignment actually lives

That split is implemented today across the shared SDK, the registry runtime/store, and the UI. The fix is to make assignment **stage-owned** and make the step editor the only primary authoring surface for assignment.

## 1. Problem Statement

### 1.1 What is wrong today

The current product asks the author to do one job in two places.

- In the step editor, the user chooses `participant_key` and sees a summary-only runtime-assignment panel.
- The actual selector editor lives on the participant editor.
- Runtime dispatch reads `participant.selector`, not the stage.

That means the user thinks:

- add a step
- decide who should do it
- choose a skill or a specific agent

But the system actually requires:

- create or pick a participant
- configure assignment on the participant
- return to the step and point it at that participant

That is a product-model problem, not just copy.

### 1.2 Where the current authority lives

Shared SDK:

- `octopus_sdk/protocols/models.py`
  - `ProtocolParticipantDefinitionRecord` currently has `selector`
  - `ProtocolStageDefinitionRecord` currently has `participant_key` but no `selector`
- `octopus_sdk/protocols/documents.py`
  - validation currently emits `participant.selector_*`
  - action/waiver follow-up still points to participant assignment
- `octopus_sdk/protocols/engine.py`
  - `dispatch_target_selector(...)` reads `participant.selector`
  - `build_dispatch_request(...)` passes `normalized_requested_skills(selector=participant.selector)`

Registry runtime and persistence:

- `octopus_registry/protocol_runtime.py`
  - calls `dispatch_target_selector(run=..., participant=document.participant(...))`
  - maps missing selector to `PARTICIPANT_SELECTOR_REQUIRED`
- `octopus_registry/protocol_store.py`
  - persists participant-selector-oriented snapshots and requested skills
  - uses participant-selector naming in execution records and store rows

UI:

- `octopus_registry/ui/js/components/protocol-workspace.js`
  - `_stageAssignmentPanel(...)` is summary-only and jumps to participant editing
  - `_participantEditorShell(...)` contains the real selector editor
  - selector preview state is participant-scoped (`selectorPreview.participantKey`)

### 1.3 User-visible impact

- `Add participant` vs `Add step` is confusing and redundant.
- A new author cannot configure a step end-to-end from the step editor alone.
- Shared participant selectors are a silent footgun because changing one participant changes multiple steps.
- Skill assignment feels broken because the real matching workflow is not owned by the step editor.

## 2. Target State

Assignment becomes **stage-owned**.

- Canonical authority: `stage.selector`
- Runtime dispatch reads the stage selector
- Validation reads the stage selector
- Selector preview is keyed to the stage editor flow
- Step editor owns assignment UI directly

Participants remain, at least initially, only for:

- stable role identity (`participant_key`)
- display name
- optional shared instructions / role-level copy
- session/group semantics that still legitimately depend on participant identity

Participants stop being the assignment authority.

## 3. Decisions

1. **One assignment authority**
   Canonical assignment lives on the stage. There is no long-term dual authority.

2. **One migration boundary**
   Legacy participant-owned selectors are converted in `documents.py` during canonicalization. After canonicalization, everything else reads stage selectors only.

3. **Step-first authoring**
   The step editor owns assignment, routing, and instructions. The author should not need to visit a participant editor to configure who runs a step.

4. **Participants become roles, not assignment containers**
   In product terms, participant becomes a role/owner concept. Selector editing is removed from that surface.

5. **No authored skill-plus-pinned-agent hybrid in phase 1**
   The authored selector is one of:
   - `agent`
   - `skill`
   - `role`

   If the user chooses a specific agent from the skill-match preview, the stage switches to `agent` mode explicitly.

6. **Rehearsal behavior is preserved**
   Rehearsal still rewrites dispatch to the reserved `role=rehearsal` selector in the engine/runtime path. This remains a runtime rule, not authored stage data.

7. **Store and API semantics move with the model**
   If HTTP or store fields use participant-selector naming for stage-owned data, they must be renamed or explicitly deprecated in the same release boundary. Do not leave external operators reading participant language for stage-owned assignment.

8. **Single release boundary**
   The SDK canonicalization change, registry runtime/store change, and UI change ship together as one cutover. No mixed deployment where runtime/store still assume participant authority after canonical documents have moved to stage authority.

## 4. Non-Goals

- Do not introduce a parallel “stage override” on top of participant selectors.
- Do not keep write-through synchronization between stage and participant selectors after cutover.
- Do not add a new top-level authoring surface.
- Do not add on-canvas connection editing as part of this migration.

## 5. Implementation Scope

This is an SDK-first change with registry/UI adoption layered on top.

### 5.1 Shared SDK

- `octopus_sdk/protocols/models.py`
- `octopus_sdk/protocols/documents.py`
- `octopus_sdk/protocols/engine.py`
- `octopus_sdk/protocols/builtins.py`
- any `octopus_sdk/registry/*` client/model contract that exposes selector ownership directly

### 5.2 Registry runtime and persistence

- `octopus_registry/protocol_runtime.py`
- `octopus_registry/protocol_store.py`
- store-backed selector preview paths
- any DB/store semantics still named around participant selectors

### 5.3 UI

- `octopus_registry/ui/js/components/protocol-workspace.js`
- any UI state, HTTP payload, or selector-preview cache keyed by participant assignment semantics

### 5.4 Tests

- protocol SDK tests
- protocol engine tests
- protocol runtime tests
- protocol store tests
- registry UI contract tests
- Playwright authoring tests

## 6. Detailed Implementation Plan

### Phase 1: Extend the shared schema

Files:

- `octopus_sdk/protocols/models.py`

Changes:

- Add `selector: TargetSelector | None = None` to `ProtocolStageDefinitionRecord`.
- Remove `selector` from the canonical role of `ProtocolParticipantDefinitionRecord`.
- Keep `participant_key` on the stage.
- Keep participant records for identity, naming, and optional shared instructions.

Rules:

- The stage now owns the dispatch rule.
- The participant no longer owns the dispatch rule.

Acceptance:

- canonical stage model supports `selector`
- canonical participant model no longer needs `selector`

### Phase 2: Canonicalize legacy documents in one place

Files:

- `octopus_sdk/protocols/documents.py`

Changes:

- During migration/canonicalization:
  - if `stage.selector` exists, keep it
  - else if the referenced participant has a selector, copy that selector onto the stage
  - strip participant selectors from the canonical output
- Keep this as the only legacy bridge.
- Do not add runtime fallback logic outside canonicalization.

Validation changes:

- Replace `participant.selector_*` issues with `stage.selector_*`
- Add or rename stage-level issues such as:
  - `stage.selector_required`
  - `stage.selector_kind_invalid`
  - `stage.selector_value_required`
- Update `_next_required_actions(...)` so actions/waivers no longer point to participant-assignment language by accident
- Audit any action or waiver text that still refers to `participants.assign_selector`

Acceptance:

- canonical document output is stage-authoritative
- participant selectors are not present in canonical document output
- validation and follow-up actions are stage-oriented

### Phase 3: Switch the engine to stage-owned assignment

Files:

- `octopus_sdk/protocols/engine.py`

Changes:

- Update `dispatch_target_selector(...)` to read the stage selector, not the participant selector.
- Preserve the existing rehearsal special case:
  - if `run.is_rehearsal`, return `TargetSelector(kind="role", value="rehearsal")`
  - otherwise use `stage.selector`
- Update `build_dispatch_request(...)` to derive `requested_skills` from `stage.selector`
- Update engine snapshot fields so selector snapshots reflect stage-owned assignment semantics

Rules:

- authored assignment source is stage-owned
- rehearsal remains a runtime-only rewrite

Acceptance:

- dispatch reads `stage.selector`
- rehearsal behavior does not regress
- requested skills are derived from stage selector only

### Phase 4: Move the registry runtime to the same contract

Files:

- `octopus_registry/protocol_runtime.py`

Changes:

- Pass `stage` into dispatch-target resolution instead of only `participant`
- Update the error mapping for missing assignment:
  - replace participant-oriented error semantics with stage-oriented ones
  - e.g. `STAGE_SELECTOR_REQUIRED` or equivalent final error code
- Keep `runtime_protocol_selector(...)` behavior aligned with the new stage-owned selector input

Acceptance:

- registry runtime no longer assumes participant-owned selectors
- blocked-run semantics point at the stage, not the participant

### Phase 5: Migrate persistence and snapshots

Files:

- `octopus_registry/protocol_store.py`
- any related SQL/store contract paths
- store tests and contracts

Changes:

- Replace any use of `participant.selector` for:
  - `normalized_requested_skills(...)`
  - selector snapshots
  - resolution metadata
- Move snapshot generation to `stage.selector`
- Rename persistence semantics that still describe stage-owned assignment as participant-owned assignment
- If DB/store/API fields are literally `participant_selector_*` for stage-owned data:
  - rename them in the same release if feasible
  - otherwise explicitly deprecate and update their documented meaning in the same release

Important:

- This phase ships together with Phase 2. The document cutover and store cutover are one release boundary.
- Do not ship canonical stage selectors while persistence still writes participant-owned selector semantics as if nothing changed.

Acceptance:

- execution/store snapshots reflect stage-owned assignment
- requested skills are persisted from stage selectors
- no new store writes depend on `participant.selector`

### Phase 6: Move preview to step-scoped semantics

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- any selector-preview HTTP client/helper used by the UI
- preview-related tests

Changes:

- Keep preview selector resolution selector-based at the transport level if possible
- Move UI preview state from participant scope to stage scope:
  - replace `selectorPreview.participantKey` semantics with stage-scoped ownership/cache keys
- Ensure preview state is updated before or at the same time as the step editor becomes assignment-authoritative
- Reuse the existing preview machinery; do not create a duplicate preview path

Acceptance:

- preview follows the step editor, not the participant editor
- no transient state where step editing owns assignment but preview still keys off participant ownership

### Phase 7: Make the step editor the assignment editor

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`

Changes:

- Remove the summary-only `_stageAssignmentPanel(...)` pattern
- Inline the selector editor directly into `_stageEditorShell(...)`
- The step editor now owns:
  - step basics
  - assignment
  - routing
  - instructions
  - artifacts
- Delete the “Edit participant assignment” jump from the step editor

UX rules:

- assignment label becomes just `Assignment`, not `Runtime assignment`
- the author should not need to leave the step editor to configure who runs the step

Acceptance:

- step editor fully configures step assignment in one place
- no participant-editor detour remains in the main step flow

### Phase 8: Demote participant editing to role management

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- related UI strings/tests

Changes:

- Remove selector editing from `_participantEditorShell(...)`
- Reframe participant editing as role management:
  - display name
  - shared instructions
  - any remaining role-level metadata
- Remove `Add participant` as a co-equal primary CTA in the main workflow authoring surface
- Keep role management accessible, but not as the primary prerequisite path

Acceptance:

- participant editor no longer competes with step editor for assignment authority
- `Add step` is the primary authoring action

### Phase 9: Add inline role creation in the step flow

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`

Changes:

- In the step editor owner field:
  - allow selecting an existing role
  - allow `Create new role…`
- If `Create new role…` is chosen, show inline fields for:
  - role name
  - optional shared instructions
- Persist the stage and role through the same save path

Dependency:

- This phase is blocked until stages carry selectors and the step editor owns assignment.

Acceptance:

- a user can add a step and create its role inline
- step creation no longer depends on understanding participant management first

### Phase 10: Make skill assignment behave like users expect

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- preview helpers/tests

Changes:

- When assignment strategy is `skill`, show matching connected agents inline in the step editor
- If the user chooses a matching agent, switch the stage selector to explicit `agent` mode
- Do not introduce authored `skill + preferred_agent_id` hybrid state in phase 1
- If zero agents match:
  - keep the warning visible in the step editor
  - validation/publish policy remains explicit and stage-based

Acceptance:

- choosing a skill visibly shows current matches
- choosing a specific matching agent becomes an explicit `agent` assignment

### Phase 11: Update templates, clients, and HTTP surface names

Files:

- `octopus_sdk/protocols/builtins.py`
- any protocol seed/template fixtures
- any `octopus_sdk/registry/*` client/model contracts
- any HTTP response fields or docs still exposing participant-owned selector naming

Changes:

- Update built-in templates to author selectors on stages
- Remove template dependence on participant-owned selectors
- Update any external/client-facing JSON fields whose names still imply participant-owned selector authority for stage data
- If a field cannot be renamed immediately, document deprecation in the same release and remove it on the next planned boundary

Acceptance:

- built-ins follow the new canonical model
- external operators do not see stage-owned data mislabeled as participant-owned data without an explicit deprecation note

### Phase 12: Delete dead paths

Files:

- SDK, registry runtime/store, UI, and tests touched above

Changes:

- Delete participant-selector-based runtime fallback logic
- Delete participant-selector-based UI flows
- Delete stale issue/action names if replaced
- Delete tests that only protect the old authority split

Acceptance:

- one coherent pipeline remains
- no duplicate authority path survives

## 7. Deployment and Release Boundary

This migration must ship as one coherent cutover.

### Required release boundary

The following must move together:

- SDK schema and canonicalization
- engine dispatch
- registry runtime dispatch wiring
- registry persistence/snapshots
- step-editor preview semantics
- UI save/editor contract

### What is allowed during rollout

- legacy input documents may still contain participant selectors
- `documents.py` canonicalization may still accept that legacy input

### What is not allowed after cutover

- runtime reading participant selectors
- store writes deriving selector data from participants
- UI persisting assignment to participants as the canonical path

### Deploy rule

- update branch
- push branch
- fast-forward `/Users/tinker/octopus`
- deploy from `/Users/tinker/octopus` only

Do not create split deployments from different working copies.

## 8. Testing Plan

### SDK and canonicalization

Update/add tests in:

- `tests/test_protocols.py`
- `tests/test_protocol_engine.py`

Required coverage:

- legacy participant selector migrates to `stage.selector`
- canonical document strips participant selectors
- `stage.selector_required` and related issues replace participant-oriented issue codes
- rehearsal dispatch still resolves to `role=rehearsal`
- `build_dispatch_request(...)` uses `stage.selector`

### Registry runtime

Update/add tests in runtime-facing coverage, including:

- `tests/test_protocol_rehearsal.py`
- any tests covering `octopus_registry/protocol_runtime.py`

Required coverage:

- missing stage selector blocks with stage-oriented error semantics
- rehearsal behavior remains unchanged
- runtime dispatch no longer depends on participant selector authority

### Store and persistence

Update/add tests in:

- `tests/contracts/test_registry_store_contract.py`
- any store tests that hit insert/update paths
- any DB/store contract tests covering selector snapshots / requested skills

Required coverage:

- stage selector drives requested skills persistence
- stage selector drives snapshot persistence
- participant-selector-named semantics are removed or explicitly deprecated as planned

### UI and Playwright

Update/add tests in:

- `tests/test_registry_ui_contract.py`
- `tests/test_registry_ui_kit_contract.py`
- `tests/e2e/playwright/protocol-ui.spec.js`

Required coverage:

- step editor contains assignment controls directly
- participant editor no longer contains selector editing
- add-step flow can create a role inline
- skill selection shows live matches in the step editor
- choosing a matching agent switches the selector to `agent`
- assignment to `M1` persists from the step editor
- no “Edit participant assignment” dependency remains in the step flow

## 9. Acceptance Criteria

The migration is complete only when all of the following are true:

1. A user can create a step and fully configure assignment without leaving the step editor.
2. `Add step` is sufficient to begin authoring; role creation can happen inline.
3. Runtime dispatch reads one authority: `stage.selector`.
4. Validation, waivers/actions, and UI language all point at stage-owned assignment.
5. Store snapshots and requested-skills persistence reflect stage-owned assignment.
6. Rehearsal dispatch still targets the reserved rehearsal role exactly as before.
7. Selector preview follows the step editor, not the participant editor.
8. Participant/role editing no longer competes with step editing for assignment authority.
9. No long-term dual authority or compatibility shim remains.

## 10. Ship Blockers

Do not ship if any of these remain true:

- `engine.py` still reads `participant.selector`
- `protocol_runtime.py` still maps missing assignment as a participant-owned selector problem
- `protocol_store.py` still writes new execution/snapshot data from participant-owned selectors
- UI preview is still keyed to participant assignment while step editor owns assignment
- participant editor still owns selector editing
- step editor still relies on an “Edit participant assignment” detour
- stage-owned data is still exposed to operators only through participant-selector-named surfaces without rename/deprecation handling

## 11. Execution Order

1. Add `stage.selector` in the shared SDK model.
2. Implement canonicalization and validation cutover in `documents.py`.
3. Switch engine dispatch to stage-owned selectors, preserving rehearsal behavior.
4. Switch registry runtime dispatch wiring and error semantics.
5. Switch store persistence and snapshot generation.
6. Switch preview/state ownership to step scope.
7. Move selector editing into the step editor.
8. Remove selector editing from participant editor and demote participant management.
9. Add inline role creation.
10. Update templates, client contracts, and HTTP/store naming.
11. Delete dead paths.
12. Run full SDK, runtime, store, and UI verification.
