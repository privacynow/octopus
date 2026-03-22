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

3. **Autonomous requires `BOT_ALLOWED_USERS`.** `BOT_ALLOW_OPEN=0` is enforced.
   Autonomous without an allowlist is a config error rejected at startup.

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
approval_explicit = "BOT_APPROVAL_MODE" in file_vars or "BOT_APPROVAL_MODE" in os.environ
if autonomous and not approval_explicit:
    approval = "off"
```

Add `autonomous=autonomous` to the BotConfig constructor call.

### Validation in `validate_config()`

After existing `codex_full_auto` / `codex_dangerous` mutual exclusion (~line 731):

- `BOT_AUTONOMOUS=1` + `BOT_ALLOW_OPEN=1` → error
- `BOT_AUTONOMOUS=1` without `BOT_ALLOWED_USERS` or `BOT_ADMIN_USERS` → error

### `load_config_provider_health()`

Add `autonomous=False` to the minimal BotConfig constructor.

### Test strategy

- `BOT_AUTONOMOUS=1` parses to `autonomous=True`
- `BOT_AUTONOMOUS=1` + `BOT_ALLOW_OPEN=1` = validation error
- `BOT_AUTONOMOUS=1` without allowed/admin users = validation error
- `BOT_AUTONOMOUS=1` + `BOT_ALLOWED_USERS` set = passes
- `BOT_AUTONOMOUS=1` without explicit `BOT_APPROVAL_MODE` defaults approval to `"off"`
- `BOT_AUTONOMOUS=1` with explicit `BOT_APPROVAL_MODE=on` keeps `"on"`
- `CODEX_DANGEROUS=1` alongside `BOT_AUTONOMOUS=1` = no error

---

## Phase 2: Dispatch — Skip Preflight

### How it works (no code change needed)

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

**No code change needed in `dispatch_message_request`.** The config default
propagates through session initialization.

### Test strategy

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
branch:

```python
if runtime.config.autonomous and not session.approval_mode_explicit:
    # Auto-submit: call the approval handler directly without buttons
    await handle_delegation_approve(...)
    return RequestExecutionOutcome(status="delegation_submitted")
```

Reuse the existing `handle_delegation_approve` in `app/agents/delegation.py`
(~line 130) which handles authority resolution, task routing submission, partial
failure, and session save.

Need a thin egress adapter that sends text inline (no buttons) for status
messages during submission.

### Partial failure handling

The existing `handle_delegation_approve` already handles partial failures:
some tasks submitted, some authority resolution fails. In autonomous mode,
failures are reported inline in the conversation. The bot continues rather than
pausing for human intervention.

### Test strategy

- `config.autonomous=True` → `handle_delegation_approve` called directly,
  no buttons rendered
- Partial failure in autonomous auto-submit: message sent to chat
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

### Test strategy

- `prompt_setup_mode` returns `autonomous`, `safe`, or `advanced`
- Autonomous writes `BOT_AUTONOMOUS=1`, `BOT_APPROVAL_MODE=off`,
  `BOT_ALLOW_OPEN=0`, `BOT_ALLOWED_USERS`
- Safe writes `BOT_AUTONOMOUS=0`, `BOT_APPROVAL_MODE=on`
- Advanced unchanged
- Workspace integration: autonomous + workspace path creates/joins workspace
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

- [ ] `BOT_AUTONOMOUS=1` + `BOT_ALLOW_OPEN=1` rejected at startup
- [ ] `BOT_AUTONOMOUS=1` without allowed users rejected at startup
- [ ] `BOT_AUTONOMOUS=1` defaults `approval_mode` to `"off"` when not explicit
- [ ] Autonomous bot skips preflight for all incoming messages
- [ ] Autonomous bot sets `skip_permissions=True` on RunContext
- [ ] Claude gets `--dangerously-skip-permissions` in autonomous mode
- [ ] Codex gets `--dangerously-bypass-approvals-and-sandbox` in autonomous mode
- [ ] `/approval on` restores preflight + removes skip\_permissions grant
- [ ] `file_policy=inspect` overrides autonomous (read-only stays read-only)
- [ ] Delegation auto-submits without buttons in autonomous mode
- [ ] Partial delegation failures reported inline
- [ ] Setup flow offers autonomous / safe / advanced
- [ ] Autonomous setup prompts for user ID and optional workspace
- [ ] Safe writes `BOT_APPROVAL_MODE=on` explicitly
- [ ] Advanced unchanged from current full mode
- [ ] `CODEX_DANGEROUS=1` alongside `BOT_AUTONOMOUS=1` no error
- [ ] All existing tests pass
- [ ] New tests cover all four runtime seams
