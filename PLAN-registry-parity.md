# Plan: Registry UI Feature Parity

## Problem statement

The registry UI is a partial operator surface. Telegram users can manage
skills per conversation, change settings, reset sessions, handle recovery
prompts, and complete credential setup flows. The registry UI cannot do
most of these.

This is not a UI-only problem. The gaps exist because some bot behaviors
were built as Telegram-specific presentation instead of SDK-level
operations. The fix is not "add buttons to the registry UI." The fix is:
make every operator action an SDK-owned workflow operation, then have both
Telegram and the registry UI call the same SDK workflow methods — Telegram
through its runtime dispatch, the registry through the management protocol.

No backward compatibility. If the SDK changes, Telegram updates in the
same commit. There are no external consumers to protect.

## Architectural principle

Two operator action paths:

**Management protocol** — operator-initiated configuration and control:
```
UI / Transport → management protocol → SDK workflow → result
```
Examples: skills, guidance, settings, credential setup.

**Coordination envelope** — operator responds to bot-pending state:
```
UI / Transport → coordination action → delivery → BotRuntime dispatch → SDK workflow
```
Examples: approve, reject, retry, recovery, delegation decisions.
Keyed by an existing pending/request/update/task/proposal ID.

Both paths call the same SDK workflow methods underneath. Telegram and
the registry UI are both consumers of the same operations.

Rules:
- No `InboundAction` delivery for management operations — management
  operations use the management protocol, not the coordination envelope
- No registry egress reclassifies events after the fact — the bot emits
  the correct event kind at the SDK level
- Recovery and retry are coordination (responses to bot-pending state)
- Settings, skills, guidance, credentials are management (operator-initiated)

## Current state

### What works end-to-end through the management protocol

Skill catalog (list, search, detail, install, uninstall, update, diff),
provider guidance (detail, preview, edit, submit, approve, reject,
publish, archive), per-conversation skill state/activate/deactivate/clear.

### What works through the coordination action envelope

Approve, reject, cancel_conversation, retry_allow, retry_skip,
recovery_replay, recovery_discard, direct_assign, delegate_tasks,
approve_delegation, cancel_delegation, cancel_task, retry_task.

### What is missing

| Feature | SDK Port | Exposed via management protocol? |
|---------|:--------:|:-------------------------------:|
| Conversation settings (compact, model, approval, role, project, file policy) | Yes (`ConversationSettingsPort`) | **NO** |
| Conversation reset | Yes (`ConversationControlPort`) | **NO** |
| Recovery prompt rendering with actionable buttons | Yes (recovery state in session) | **NO** — emitted as `error` event, not actionable |
| Retry prompt rendering with actionable buttons | Yes (approval with `request_kind`) | Partially — event exists, UI doesn't render buttons |
| Credential setup flow | Yes (`RuntimeSkillSetupPort`) | **NO** |
| Per-conversation skills UI in conversation detail | Yes (endpoints exist) | Yes (endpoints exist, UI doesn't use them) |
| Settings read (current values + available options) | Yes (session + config) | **NO** |

## Principles

1. Every configuration/control action (settings, skills, guidance,
   credentials) is a management protocol operation with typed SDK
   request/result models. Coordination actions (approve, reject, retry,
   recovery) stay on the coordination envelope.
2. Settings mutations go through the management protocol, NOT through
   the coordination action envelope as `InboundAction` deliveries.
   Settings are bot management operations, same category as skills and
   guidance.
3. Recovery events are emitted as `approval.requested` with
   `request_kind="recovery"` at the SDK level (in the event sink), not
   reclassified by the registry egress after the fact. The bot emits
   the correct kind. All transports see the same event.
4. Credential setup uses the SAME SDK `RuntimeSkillSetupPort` method
   from both Telegram and the management executor. Not two paths.
5. The activation picker filters by `can_activate=true` from the catalog.
6. No backward compatibility concerns — Telegram updates in the same
   commit as SDK changes.

## Phase 1: Per-conversation skills UI + actionable event buttons

### 1a: Skills panel in conversation detail

Endpoints and API wrappers already exist. This is UI wiring plus one
backend fix (WS broadcast).

- [ ] 1a-1: Add a "Skills" section to conversation detail. Load BOTH:
  - `API.getConversationSkills(agentId, convoId)` for active skills
  - `API.listSkills(agentId)` for available catalog (via management protocol)
  Show active skills as a list. Show activation dropdown from catalog,
  filtered to exclude already-active AND filtered by `can_activate=true`
  (`management.py:74`).

- [ ] 1a-2: Each active skill row has a "Deactivate" button:
  `API.deactivateConversationSkill(agentId, convoId, skillName)`.

- [ ] 1a-3: Activation dropdown on selection:
  `API.activateConversationSkill(agentId, convoId, skillName)`.

- [ ] 1a-4: Handle `needs_setup` → show credential form (Phase 3).
  Handle `foreign_setup` (409) → show "Another user is setting up."

- [ ] 1a-5: Handle `projected_size` / `prompt_size_threshold` warnings.
  `confirm` parameter allows re-submission after acknowledgment.

- [ ] 1a-6: "Clear all skills" button:
  `API.clearConversationSkills(agentId, convoId)`.

- [ ] 1a-7: **Backend:** Skill mutation server endpoints
  (`server.py:1383-1454`) must broadcast WS conversation invalidation
  after mutation. The conversation detail view must be updated to refresh
  the skills panel on `invalidate` messages (currently it only reacts to
  `progress` and `event` at `conversation-detail.js:971`). Skill
  mutations are management operations, not conversation events — do NOT
  fabricate conversation events for management writes. Use invalidation
  so the view refetches the skills state.

- [ ] 1a-8: After mutation, optimistic UI refresh + WS confirmation.

### 1b: Recovery action buttons

**SDK change required:** Recovery events must be emitted as
`approval.requested` with `request_kind="recovery"` at the source —
in the SDK event sink or the execution path that detects stale/crashed
sessions. NOT reclassified by the registry egress.

- [ ] 1b-1: **SDK event schema:** Widen `ApprovalRequestedMetadata.request_kind`
  in `octopus_sdk/events.py:90` to include `"recovery"` alongside the
  existing `"preflight"`, `"retry"`, and `"delegation"` values.

- [ ] 1b-2: **SDK event emission:** Change recovery event emission from
  `error` to `approval.requested` with `request_kind="recovery"` in the
  SDK execution/recovery path, NOT in `egress.py`. Include the numeric
  `update_id` in the event metadata so the coordination action can
  reference it. The `ApprovalRequestedMetadata` schema may need an
  optional `update_id: int | None` field for recovery events.

- [ ] 1b-3: **SDK action payload:** Verify `RecoveryActionPayload` in
  `octopus_sdk/registry/models.py:568` — it requires `update_id: int`.
  The recovery event metadata must carry this same numeric `update_id`
  so the UI can extract it and include it in the action payload.
  Do NOT use `event.event_id` (string) as `update_id` (int) — they are
  different types and different identifiers.

- [ ] 1b-4: **Telegram:** Update Telegram recovery rendering to detect
  the new event kind. Same commit as 1b-1/1b-2.

- [ ] 1b-5: **Registry UI:** In `event-renderers.js`, detect recovery
  via `event.kind === 'approval.requested'` and
  `metadata.request_kind === 'recovery'`.

- [ ] 1b-6: Render "Replay" and "Discard" buttons. Extract numeric
  `update_id` from the event metadata (NOT from `event.event_id`):
  `API.conversationAction(convoId, 'recovery_replay', { update_id: metadata.update_id })`
  or `recovery_discard` with same payload.

- [ ] 1b-7: Disable after click. Show status text.

### 1c: Retry decision buttons

Retry prompts are already `approval.requested` events with the right
structure. The UI just doesn't render action buttons for them.

- [ ] 1c-1: In `event-renderers.js`, detect retry via
  `event.kind === 'approval.requested'` and
  `metadata.request_kind === 'retry'`.

- [ ] 1c-2: Render "Allow" and "Skip" buttons using `event.event_id`
  as `request_id` (same pattern as approve/reject at
  `event-renderers.js:231`):
  `API.conversationAction(convoId, 'retry_allow', { request_id: event.event_id })`
  or `retry_skip`.

- [ ] 1c-3: Disable after click. Show status text.

### Phase 1 exit gate

- Skills section with activate/deactivate/clear in conversation detail
- Activation picker filters by `can_activate=true`
- Recovery events emitted as `approval.requested` at SDK level
- Recovery Replay/Discard buttons in registry UI
- Retry Allow/Skip buttons in registry UI
- WS broadcast on skill mutations
- Telegram recovery rendering updated for new event kind

## Phase 2: Conversation settings via management protocol

Settings are bot management operations. They go through the management
protocol with typed request/result models, same as skills and guidance.
NOT through the coordination action envelope as `InboundAction`.

### 2a: SDK management operations for settings

- [ ] 2a-1: Add to `octopus_sdk/registry/management.py`:
  - `GetConversationSettingsRequest(conversation_id: str)`
  - `GetConversationSettingsResult` with:
    - Current values: `compact_mode`, `model_profile`, `approval_mode`,
      `role`, `project`, `file_policy` (from session)
    - Available options: `model_profiles` list, `file_policies`
      (`["inspect", "edit"]`), `projects` list, `default_role`
      (from bot config). Role is free-form text — return `default_role`
      for a "Reset to default" option, not a role options list.
  - `SetConversationSettingRequest(conversation_id, setting, value)`
  - `SetConversationSettingResult(status, setting, value)`
  - `ResetConversationRequest(conversation_id)`
  - `ResetConversationResult(status)`

- [ ] 2a-2: Add management executor handlers in
  `management_executor.py`:
  - `get_conversation_settings` → reads session + config
  - `set_conversation_setting` → calls the appropriate
    `ConversationSettingsPort` method based on `setting` name
  - `reset_conversation` → calls `ConversationControlPort.reset_session`
  The executor calls the SAME SDK workflow methods that Telegram calls
  through its runtime dispatch. Same workflows, different entry points.

- [ ] 2a-3: Add ingress functions in `ingress.py` for each operation.

- [ ] 2a-4: Add server endpoints:
  - `GET /v1/agents/{agent_id}/conversations/{id}/settings`
  - `POST /v1/agents/{agent_id}/conversations/{id}/settings`
    (body: `{ setting, value }`)
  - `POST /v1/agents/{agent_id}/conversations/{id}/reset`

- [ ] 2a-5: Add API wrappers in `api.js`:
  `getConversationSettings`, `setConversationSetting`,
  `resetConversation`.

### 2b: Settings UI in conversation detail

- [ ] 2b-1: Add "Settings" section. On load, call
  `API.getConversationSettings(agentId, convoId)`.

- [ ] 2b-2: Compact mode: toggle. On change:
  `API.setConversationSetting(agentId, convoId, 'compact_mode', value)`.

- [ ] 2b-3: Model profile: dropdown populated from
  `result.available.model_profiles`. On change:
  `API.setConversationSetting(agentId, convoId, 'model_profile', value)`.

- [ ] 2b-4: Approval mode: toggle (`on`/`off` only — the SDK contract
  at `conversation_settings.py:72` only accepts these two values).

- [ ] 2b-5: File policy: dropdown populated from
  `result.available.file_policies` (`inspect`/`edit` per
  `conversation_settings.py:219`).

- [ ] 2b-6: Project: dropdown populated from `result.available.projects`
  (configured project names per `conversation_settings.py:178`). NOT
  free-form text — `set_project` only accepts configured names or "clear".

- [ ] 2b-7: Role: text input with current value. "Reset to default"
  button that sends empty string (resets to `default_role`).

- [ ] 2b-8: Reset conversation: button with confirmation dialog.
  `API.resetConversation(agentId, convoId)`.

- [ ] 2b-9: Refresh on WS events. If management request fails, show
  "Settings unavailable — bot not connected."

### Phase 2 exit gate

- All settings operations go through management protocol
- NOT through coordination action envelope
- Settings read returns current values AND available options
- All controls match the real SDK contract values
- Telegram and registry UI both call the same SDK workflow methods.
  Registry reaches them through the management executor. Telegram
  reaches them through its runtime/command dispatch path.
- No `InboundAction` delivery for settings mutations

## Phase 3: Browser-based credential setup

### Design

The credential setup uses the SAME `RuntimeSkillSetupPort` methods that
Telegram uses. The management executor calls the same workflow. The only
difference is presentation: Telegram prompts via chat messages, the
registry prompts via a form.

The bot owns the requirement sequence via `SessionState.awaiting_skill_setup`.
The browser sends only values, not requirement names.

### 3a: SDK management operations for credential setup

- [ ] 3a-1: Add to `management.py`:
  - `SubmitCredentialValueRequest(conversation_id, skill_name, actor_key, value)`
    `actor_key` is required — `runtime_skill_setup.py:156` validates
    the actor matches who started setup.
    Does NOT carry `requirement_name` — the bot knows which requirement
    is pending from session state.
  - `SubmitCredentialValueResult(status, next_requirement, error)`
    Status: `accepted`, `validation_failed`, `next_requirement`, `complete`.

- [ ] 3a-2: Management executor handler: loads session, reads
  `awaiting_skill_setup`, calls
  `workflows.runtime_skills.setup.submit_credential_value()` with
  value and actor_key. Same method Telegram calls.

- [ ] 3a-3: Ingress function + server endpoint:
  `POST /v1/agents/{agent_id}/conversations/{cid}/skills/{name}/credential`

- [ ] 3a-4: API wrapper in `api.js`:
  `submitConversationSkillCredential(agentId, convoId, skillName, body)`

### 3b: Credential setup UI

- [ ] 3b-1: When activation returns `needs_setup` with
  `first_requirement`, show a credential form.

- [ ] 3b-2: Form: requirement name as label, description as help text,
  text input (type=password if `is_secret`), Submit button.

- [ ] 3b-3: On submit: `API.submitConversationSkillCredential()`.
  Disable form during management request.

- [ ] 3b-4: On `validation_failed`: show error inline, re-enable form.

- [ ] 3b-5: On `next_requirement`: replace form with next requirement.

- [ ] 3b-6: On `complete`: close form, refresh skills panel, show success.

- [ ] 3b-7: On `foreign_setup`: show conflict message.

- [ ] 3b-8: No credential values stored in browser. Form clears on submit.

### Phase 3 exit gate

- Credential setup works end-to-end from registry UI
- Same SDK workflow method called from both Telegram and management executor
- Browser sends values only, bot owns requirement sequence
- Secrets use password input, not stored in browser
- actor_key validated by the setup machine

## Execution order

```
Phase 1 (skills UI + event buttons + SDK recovery event fix)
Phase 2 (settings via management protocol)
Phase 3 (credential setup via management protocol)
```

- Phase 1 includes one SDK change (recovery event kind)
- Phase 2 adds new management operations (settings read/write/reset)
- Phase 3 adds one management operation (credential submission)
- Phase 3 depends on Phase 1a (skills panel must exist)

## Exit criteria

1. Per-conversation skills section in conversation detail with
   activate/deactivate/clear. Activation filtered by `can_activate`.
2. Recovery events emitted as `approval.requested` at SDK level with
   `request_kind="recovery"`. Telegram updated in same commit.
3. Recovery Replay/Discard and Retry Allow/Skip buttons in registry UI.
4. Conversation settings readable and writable from registry UI via
   management protocol operations. NOT via coordination envelope.
5. Settings read returns current values AND available options from bot
   config (model profiles, file policies, projects, default role).
6. All settings controls use correct SDK contract values (approval mode
   `on`/`off`, file policy `inspect`/`edit`, project from configured
   list).
7. Browser-based credential setup form works end-to-end. Same SDK
   workflow method as Telegram. actor_key required. No secrets stored.
8. WS broadcast on skill mutations for cross-view propagation.
9. Every management operation (settings, skills, guidance, credentials)
   follows: management protocol → SDK workflow. Coordination actions
   (approve, reject, retry, recovery, delegation decisions) follow
   the coordination envelope. No `InboundAction` delivery for
   management operations.
10. Telegram and registry UI both call the same SDK workflow methods.
    Registry reaches them through the management executor. Telegram
    reaches them through its runtime/command dispatch.

## Developer prompt

```
Bring the registry UI to feature parity with Telegram as defined in
PLAN-registry-parity.md.

Two operator action paths:
- Management protocol for configuration/control (settings, skills,
  guidance, credentials) with typed SDK request/result models
- Coordination envelope for responses to bot-pending state (approve,
  reject, retry, recovery, delegation decisions)
Both call the same SDK workflow methods that Telegram calls.

Phase 1: Skills panel in conversation detail (existing endpoints +
activation from catalog filtered by can_activate). Recovery event emission
changed from error to approval.requested at SDK level (not registry
egress reclassification). Update Telegram in same commit. Recovery
Replay/Discard and Retry Allow/Skip buttons in registry UI.

Phase 2: Settings via management protocol. New operations:
GetConversationSettings (returns current values + available options from
bot config), SetConversationSetting, ResetConversation. NOT via
coordination action envelope. Approval mode is on/off. File policy is
inspect/edit. Project is from configured list, not free text.

Phase 3: Credential setup via management protocol. New operation:
SubmitCredentialValue with actor_key. Bot owns requirement sequence.
Browser sends values only. Same SDK workflow method as Telegram.

Rules:
- All management operations follow the existing management protocol pattern
- No InboundAction delivery for management operations
- Recovery events emitted at SDK level, not reclassified in egress
- Settings go through management protocol, not coordination envelope
- Same SDK workflow methods called from both Telegram and management executor
- No backward compatibility concern — Telegram updates in same commit
- No credential values stored in browser
- can_activate filter on activation picker
```
