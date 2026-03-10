---
name: progress-ux-audit
description: Use when changing provider progress, long-output handling, compact/full/raw/export rendering, or user-visible provider errors. Enforces provider-neutral wording, no internal leakage, and liveness rules.
---

# Progress UX Audit

Use this skill for changes to progress, liveness, or user-visible
rendering around long-running requests.

## Rules

- provider-neutral wording for normal users
- no thread IDs, session IDs, provider names, or internal terminology
- heartbeat only for idle non-content states
- streamed content should not be overwritten by liveness noise
- compact/full/raw/export should derive from a stable source of truth
- user-visible assertions must follow the same message object chain the
  UI uses

## Workflow

1. **List every user-visible progress source**
   - initial status
   - provider progress
   - timeout text
   - terminal status
   - compact/full rendering
   - which object owns each rendered string

2. **Separate bot-owned status from model-owned content**
   - bot-owned waiting states may get heartbeat
   - model-owned streamed content should not be decorated heuristically

3. **Check provider parity**
   - Claude-like path
   - Codex-like path
   - any debug/operator surfaces should stay separate from end-user copy
   - adjacent provider error cases should not trigger the same reset or
     terminal wording unless the signal is specific

4. **Check terminal behavior**
   - completed / response-below / delete-status strategy must be
     explicit

5. **Test the interaction**
   - heartbeat + provider progress together
   - long output + compact mode
   - error formatting without leaking internals
   - status message created by `reply_text()` and updated via
     `edit_text()` on the returned object

## Completion Bar

Do not stop at string replacement. Verify that the interaction between
progress producers and the renderer still behaves correctly on the same
surface the user sees.
