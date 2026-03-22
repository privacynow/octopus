# Implementation Plan: Setup Modes (Autonomous / Safe / Advanced) and BOT\_AUTONOMOUS

## Overview

This plan replaces the current quick/full setup dichotomy with three
trust-posture-based modes (autonomous, safe, advanced) and introduces
`BOT_AUTONOMOUS=1` as a single policy flag with four runtime seams: config
validation, dispatch preflight skip, execution skip\_permissions, and delegation
auto-submit.

## Architectural Decisions

1. **Three setup modes replacing quick/full.** Autonomous = full agent, no
   approval gates, full provider permissions, private. Safe = guarded assistant,
   human reviews plans, public-ok, sandboxed. Advanced = configure everything
   manually (current full mode).

2. **`BOT_AUTONOMOUS=1` is one policy flag with four runtime seams.** Config
   validation (mutual exclusion with open access), dispatch (skip preflight),
   execution (skip\_permissions on RunContext), delegation (auto-submit plans).

3. **Autonomous requires non-empty `BOT_ALLOWED_USERS` and `BOT_ALLOW_OPEN=0`.**
   `BOT_ADMIN_USERS` alone does not satisfy this — admin is a skill-management
   concept, not bot access. Autonomous without an explicit allowlist is a config
   error rejected at startup.

4. **Autonomous writes both `BOT_AUTONOMOUS=1` and `BOT_APPROVAL_MODE=off`** for
   transparency. At runtime, `BOT_AUTONOMOUS` is authoritative for skipping
   preflight and granting skip\_permissions. If operator explicitly sets
   `BOT_APPROVAL_MODE=on` alongside `BOT_AUTONOMOUS=1`, the explicit
   session-level approval mode wins via `session.approval_mode_explicit`.

5. **Safe mode writes `BOT_AUTONOMOUS=0` and `BOT_APPROVAL_MODE=on`** explicitly
   (current quick never wrote these).

6. **Registry/system ingress:** `BOT_AUTONOMOUS=1` grants full autonomy to all
   work entering the bot. Registry-sourced deliveries are machine-to-machine.
   The autonomous flag applies unconditionally to registry work.

7. **`skip_permissions=True` makes `CODEX_DANGEROUS` redundant** when autonomous.
   Document this; do not error on both being set.

8. **Session override:** `/approval on` still works per-chat.
   `session.approval_mode_explicit` is respected. When explicit and set to
   `"on"`, it overrides the autonomous default for that chat.

9. **`file_policy=inspect` stays authoritative.** Autonomous does not bypass
   read-only workspace mode. Codex `run()` forces `sandbox="read-only"` when
   `file_policy == "inspect"`, and this check precedes `skip_permissions`.

10. **Workspace integration.** Autonomous setup optionally prompts for a
    workspace directory and auto-joins using existing `./octopus workspace`
    infrastructure.

---

## Phase 1: Config + Validation

### Files to modify

| File | Change |
|---|---|
| `app/config.py` | Add `autonomous: bool` field, parse `BOT_AUTONOMOUS`, adjust `approval_mode` default, validation |

### BotConfig changes

Add field after `approval_mode` (line ~221):

```python
autonomous: bool  # BOT_AUTONOMOUS: skip preflight + grant skip_permissions for trusted/registry work
```

### Parsing changes in `load_config()`

After existing approval parsing (~line 453):

```python
autonomous = get_bool("BOT_AUTONOMOUS")
# In Docker, the bot .env is loaded into os.environ by compose. Check whether
# the key is present at all — if so, the operator explicitly set it.
approval_explicit = "BOT_APPROVAL_MODE" in os.environ
if autonomous and not approval_explicit:
    approval = "off"
```

Add `autonomous=autonomous` to the BotConfig constructor call.

### Validation in `validate_config()`

After existing `codex_full_auto` / `codex_dangerous` mutual exclusion (~line 731):

- `BOT_AUTONOMOUS=1` + `BOT_ALLOW_OPEN=1` → error
- `BOT_AUTONOMOUS=1` without non-empty `BOT_ALLOWED_USERS` → error
  (`BOT_ADMIN_USERS` alone does not satisfy this)

### `load_config_provider_health()`

Add `autonomous=False` to the minimal BotConfig constructor.

### Test strategy

- `BOT_AUTONOMOUS=1` parses to `autonomous=True`
- `BOT_AUTONOMOUS=1` + `BOT_ALLOW_OPEN=1` = validation error
- `BOT_AUTONOMOUS=1` without `BOT_ALLOWED_USERS` = validation error
- `BOT_AUTONOMOUS=1` with only `BOT_ADMIN_USERS` (no `BOT_ALLOWED_USERS`) = validation error
- `BOT_AUTONOMOUS=1` + `BOT_ALLOWED_USERS` set = passes
- `BOT_AUTONOMOUS=1` without explicit `BOT_APPROVAL_MODE` defaults approval to `"off"`
- `BOT_AUTONOMOUS=1` with explicit `BOT_APPROVAL_MODE=on` keeps `"on"`
- `CODEX_DANGEROUS=1` alongside `BOT_AUTONOMOUS=1` = no error

---

## Phase 2: Dispatch — Skip Preflight

### How it works (likely no code change, but must verify)

`dispatch_message_request` at `requests.py` ~352 checks:

```python
if not routed_task_id and not skip_approval and approval_mode == "on":
```

When `config.autonomous=True` and `BOT_APPROVAL_MODE` not explicitly set, the
config default sets `approval_mode="off"`. Session is created with
`approval_mode="off"`. The existing check correctly skips preflight.

When user types `/approval on`, `session.approval_mode_explicit` becomes True
and `session.approval_mode` becomes `"on"`. This correctly re-enables preflight
for that chat only.

**Must verify:** The claim depends on fresh sessions inheriting
`config.approval_mode`. Trace the exact path: new chat → session not in
storage → `load_runtime_session` creates a default → what `approval_mode` does
the fresh `SessionState` get? The dataclass default at `session_state.py:200`
is `approval_mode=d.get("approval_mode", "off")` — but that's deserialization
from dict, not fresh creation. The fresh-creation path must be traced and
tested explicitly. If `SessionState()` defaults `approval_mode` to something
other than `config.approval_mode`, a small change is needed to pass the config
default at creation time.

**Code change:** Likely none in `dispatch_message_request` itself, but
potentially a small change in session creation to pass `config.approval_mode`
as the default for new sessions. This must be determined during implementation.

### Test strategy (required, not optional)

- **First-message / new-session test:** Brand new chat on an autonomous bot
  (no session in storage) → first message → `request_approval` is never called,
  execution proceeds directly. This proves the config default propagates
  through session creation.
- When `config.autonomous=True` and resolved `approval_mode="off"`,
  `request_approval` is never called
- `/approval on` in autonomous bot still triggers preflight

---

## Phase 3: Execution — skip\_permissions

### Files to modify

| File | Change |
|---|---|
| `app/workflows/execution/requests.py` | Grant `skip_permissions` when autonomous |

### `execute_request` changes (~line 202)

Current code:

```python
context.skip_permissions = skip_permissions
```

Replace with:

```python
autonomous_grant = cfg.autonomous and session.approval_mode != "on"
context.skip_permissions = skip_permissions or autonomous_grant
```

This grants `skip_permissions` when:
- `config.autonomous=True`, AND
- The session's approval mode is not explicitly `"on"` (operator override)

The check `session.approval_mode != "on"` correctly handles both cases:
- Session inherits the config default `"off"` → autonomous grant applies
- Session explicitly set to `"on"` via `/approval on` → grant does not apply
- Session explicitly set to `"off"` → grant applies

### Provider flow-through (no changes)

- **Claude:** `claude.py` ~401-403 injects `--dangerously-skip-permissions` when
  `context.skip_permissions` is True. Already wired.
- **Codex:** `codex.py` ~633-638 injects
  `--dangerously-bypass-approvals-and-sandbox` when `context.skip_permissions`
  and not `is_resume` and flag not already present. Already wired.

### Test strategy

- `config.autonomous=True` with default session → `context.skip_permissions` True
- `config.autonomous=True` with `session.approval_mode="on"` → `skip_permissions` not granted by autonomous
- `config.autonomous=False` → no change to existing behavior
- Existing skip\_permissions provider tests continue to pass

---

## Phase 4: Delegation Auto-Submit

### Files to modify

| File | Change |
|---|---|
| `app/channels/telegram/delegation_channel.py` | Auto-submit when autonomous |

### Changes to `propose_delegation_plan`

After building the delegation plan and saving session state, add an autonomous
branch. **The condition must match execution (Phase 3):**

```python
if cfg.autonomous and session.approval_mode != "on":
    # Auto-submit: call the approval handler directly without buttons
    await _auto_submit_delegation(...)
    return RequestExecutionOutcome(status="delegation_submitted")
```

**Not `not session.approval_mode_explicit`.** If a user runs `/approval off`
explicitly, `approval_mode_explicit=True` but `approval_mode="off"`. The old
condition would skip auto-submit even though approval is off. Using
`session.approval_mode != "on"` is consistent with the execution grant in
Phase 3 and handles all edge cases the same way.

### Delegation wiring (this is real work, not a one-liner)

`handle_delegation_approve` in `app/agents/delegation.py` (~line 130) expects:
- A real channel egress that can `send_text` for status messages
- A valid `conversation_ref` for the chat
- Correct `chat_id` for session state reload after mutation
- The session must have `pending_delegation` in `proposed` state

The auto-submit path must:
1. Build an egress adapter that sends text to the conversation without
   reply\_markup (no buttons). This is a real adapter, not a stub — it must
   use the actual Telegram send path (or registry egress for registry-sourced
   conversations) so messages are delivered.
2. Call `handle_delegation_approve` with the adapter, passing the correct
   `conversation_ref` and `chat_id`.
3. Reload session after `handle_delegation_approve` returns to check final
   delegation status.
4. If `pending_delegation.status == "submitted"`: return success.
5. If submission failed mid-flight: `pending_delegation` must not be stuck in
   `proposed` state. `handle_delegation_approve` should transition it to
   `cancelled` or `partial_failed` on error — verify this is the case.

### Failure mode: stuck `pending_delegation`

If `handle_delegation_approve` raises or fails partway through, the session
may have `pending_delegation` stuck in `proposed`. The auto-submit path must
catch errors and transition the delegation to a terminal state, or the next
message in this chat will see a stale `pending_delegation` and behave
incorrectly.

Exit gate: no stuck `pending_delegation` after auto-submit failure.

### Test strategy

- `cfg.autonomous=True` and `session.approval_mode != "on"` →
  `handle_delegation_approve` called directly, no buttons rendered
- `cfg.autonomous=True` and `session.approval_mode == "on"` (explicit) →
  buttons rendered as normal
- Partial failure in autonomous auto-submit: message sent to chat, delegation
  transitions to terminal state
- Auto-submit error: `pending_delegation` not stuck in `proposed`
- No double messages (auto-submit sends status once, not twice)
- Non-autonomous: existing button flow unchanged (regression)

---

## Phase 5: Setup Flow UX (octopus CLI)

### Files to modify

| File | Change |
|---|---|
| `octopus` | Replace `prompt_setup_mode_hatch`, modify `prepare_new_bot_setup`, `write_first_bot_env` |

### Replace `prompt_setup_mode_hatch` with `prompt_setup_mode`

```
Setup mode:
  1. Autonomous — full agent, no approval gates, private
  2. Safe — human reviews plans before execution (default)
  3. Advanced — configure everything manually
Choose a mode [2]:
```

Default is Safe (press Enter).

### Autonomous setup flow

After selecting autonomous:
1. Prompt for Telegram user ID (required, numeric)
2. Prompt for workspace directory (optional)
3. Provider selection (same as today)

No other prompts. Everything else is defaulted.

### `write_first_bot_env` mode-specific defaults

| Env var | Autonomous | Safe | Advanced |
|---|---|---|---|
| `BOT_AUTONOMOUS` | `1` | `0` | Operator choice |
| `BOT_APPROVAL_MODE` | `off` | `on` | Operator choice |
| `BOT_ALLOW_OPEN` | `0` | `1` | Operator choice |
| `BOT_ALLOWED_USERS` | Prompted ID | Not set | Operator choice |

### Workspace integration

After bot env is written and bot is running, if workspace path was provided:
- Derive workspace slug from directory basename
- Create workspace if it doesn't exist
- Add bot to workspace

**Cross-plan dependency:** Autonomous bots that join a workspace use the
compose override from `PLAN-shared-workspaces.md`. The local override
(`docker-compose.workspace.yml`) must contain only `bot` + `bot-provider` —
not `bot-webhook` / `bot-worker` which would break `bot_compose`. This is
already fixed in the workspace implementation (split local vs shared overrides).
Add a test: autonomous setup → workspace join → `bot_compose` → valid compose.

### Safe mode note

Safe mode writes `BOT_ALLOW_OPEN=1` without `BOT_ALLOWED_USERS`, matching
current `write_first_bot_env` behavior when the allowlist is empty (quick setup
posture). This is the same operator intent as the old quick mode, but with
explicit `BOT_AUTONOMOUS=0` and `BOT_APPROVAL_MODE=on` in the `.env`.

### Test strategy

- `prompt_setup_mode` returns `autonomous`, `safe`, or `advanced`
- Autonomous writes `BOT_AUTONOMOUS=1`, `BOT_APPROVAL_MODE=off`,
  `BOT_ALLOW_OPEN=0`, `BOT_ALLOWED_USERS`
- Safe writes `BOT_AUTONOMOUS=0`, `BOT_APPROVAL_MODE=on`, `BOT_ALLOW_OPEN=1`
- Advanced unchanged
- Workspace integration: autonomous + workspace path creates/joins workspace
- Workspace compose: autonomous bot with workspace → `bot_compose` produces
  valid compose config (no image-less services)
- Existing `--full` flag still works via advanced mode

---

## Delivery Slices

### Slice 1: Config field + validation

- Add `autonomous: bool` to BotConfig
- Parse from `BOT_AUTONOMOUS`
- Approval mode default logic
- Validation rules
- Tests in `tests/test_config.py`

### Slice 2: Execution skip\_permissions grant

- Modify `execute_request` for autonomous skip\_permissions
- Tests

### Slice 3: Delegation auto-submit

- Modify `propose_delegation_plan` for autonomous auto-submit
- Egress adapter
- Tests

### Slice 4: Setup flow UX

- Replace prompt\_setup\_mode\_hatch with three-option prompt
- Autonomous/safe/advanced defaults in write\_first\_bot\_env
- Workspace auto-join for autonomous
- Setup flow tests

### Slice 5: Documentation and polish

- Document `BOT_AUTONOMOUS` in help and README
- Document `CODEX_DANGEROUS` redundancy
- Update `cmd_help` output

---

## Exit Gates

### Config + validation
- [ ] `BOT_AUTONOMOUS=1` + `BOT_ALLOW_OPEN=1` rejected at startup
- [ ] `BOT_AUTONOMOUS=1` without `BOT_ALLOWED_USERS` rejected at startup
- [ ] `BOT_AUTONOMOUS=1` with only `BOT_ADMIN_USERS` (no allowed users) rejected
- [ ] `BOT_AUTONOMOUS=1` defaults `approval_mode` to `"off"` when not explicit
- [ ] `CODEX_DANGEROUS=1` alongside `BOT_AUTONOMOUS=1` no error

### Dispatch (preflight skip)
- [ ] First message on brand-new chat (no session) on autonomous bot skips
  preflight — proves config default propagates through session creation
- [ ] Autonomous bot skips preflight for all incoming messages
- [ ] `/approval on` in autonomous bot restores preflight for that chat

### Execution (skip\_permissions)
- [ ] Autonomous bot sets `skip_permissions=True` on RunContext
- [ ] Claude gets `--dangerously-skip-permissions` in autonomous mode
- [ ] Codex gets `--dangerously-bypass-approvals-and-sandbox` in autonomous mode
- [ ] `/approval on` removes skip\_permissions grant for that chat
- [ ] `file_policy=inspect` overrides autonomous (read-only stays read-only)

### Delegation (auto-submit)
- [ ] Delegation auto-submits without buttons when autonomous + approval != on
- [ ] Delegation shows buttons when autonomous + `/approval on` explicit
- [ ] Partial delegation failures reported inline, delegation reaches terminal state
- [ ] No stuck `pending_delegation` in `proposed` state after auto-submit failure
- [ ] No double messages during auto-submit

### Setup flow
- [ ] Setup offers autonomous / safe / advanced
- [ ] Autonomous prompts for user ID and optional workspace
- [ ] Autonomous writes `BOT_AUTONOMOUS=1`, `BOT_APPROVAL_MODE=off`,
  `BOT_ALLOW_OPEN=0`, `BOT_ALLOWED_USERS`
- [ ] Safe writes `BOT_AUTONOMOUS=0`, `BOT_APPROVAL_MODE=on`, `BOT_ALLOW_OPEN=1`
- [ ] Advanced unchanged from current full mode
- [ ] Autonomous + workspace → `bot_compose` produces valid compose config

### Regression
- [ ] All existing tests pass
- [ ] New tests cover all four runtime seams
