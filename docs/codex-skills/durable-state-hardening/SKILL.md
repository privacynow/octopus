---
name: durable-state-hardening
description: Use when touching sessions, work items, update journals, retries, claims, queues, or managed store state. Focuses on state transitions, commit points, replayability, and recovery tests.
---

# Durable State Hardening

Use this skill whenever correctness depends on durable state.

## When to use

- sessions or session schema
- updates / update_id tracking
- work items / queue state / claims
- approval or retry persistence
- managed capability/store refs or objects

## Workflow

1. **Write the state machine**
   - possible states
   - who transitions them
   - what success looks like
   - what failure looks like
   - what interruption/replay looks like
   - what happens if replay or recovery is interrupted again

2. **Find commit points**
   - what becomes durable first?
   - what must not be partially committed?
   - what must be replayable after restart?
   - who is allowed to finalize `done`, `failed`, or replayable state

3. **Treat in-memory state as optimization only**
   - correctness must survive restart
   - in-memory caches/locks may assist but cannot be authoritative

4. **Audit failure cleanup**
   - interrupt
   - timeout
   - exception
   - duplicate delivery
   - early return
   - second interruption during recovery
   - ambiguous errors that should not trigger destructive reset

5. **Test durable behavior**
   - success path
   - failure/interruption path
   - duplicate/idempotency path
   - recovery/restart path if applicable
   - interrupted replay vs interrupted original path
   - adjacent false-positive path for any reset or invalidation

## Red Flags

- `finally` marking durable work complete regardless of failure
- replay path swallowing the signal that the true owner needs to decide
  completion
- creating visible durable artifacts before verification
- assuming process memory is still available after restart
- skipping cleanup when a handler returns early
- destructive reset keyed off a generic error code or generic error text
