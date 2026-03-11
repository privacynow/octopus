---
name: invariant-test-builder
description: Use when a change spans multiple features or state axes. Builds parameterized invariant tests, real entry-point coverage, adjacent regression tests, and negative capability checks.
---

# Invariant Test Builder

Use this skill for cross-cutting changes where happy-path tests are not
enough.

## Core idea

Test the contract at the real boundary, then test the nearest way it
could still be wrong.

## Workflow

1. **Identify the axes**
   Examples:
   - trust x model
   - project x approval
   - policy x provider config
   - progress x long output
   - work items x interrupts x retries

2. **Choose the invariant**
   Examples:
   - cannot escalate
   - stale state invalidates
   - forbidden thing cannot happen
   - equivalent paths produce the same behavior
   - if the analysis found multiple bugs, assign one invariant per bug
     before writing combined tests

3. **Add three layers**
   - focused contract test
   - real entry-point integration test
   - adjacent regression test
   - for classification logic, make the adjacent test a false-positive
     boundary when possible

4. **Assert both output and state**
   - what the user sees
   - what durable/runtime state became
   - name the oracle explicitly: original message, returned status
     message, chat send buffer, or persisted state

5. **Prefer negative capability tests**
   - inspect cannot become writable
   - public user cannot escalate model
   - wrong user callback cannot mutate state
   - failed install cannot leave residue
   - fix for condition X must not also fire on adjacent condition Y

6. **Check message chains when testing UI text**
   - if `reply_text()` returns a new status message and later edits land
     on that object, assert on the returned message, not only the
     original message handle

## Bug report handoff

When the output is a bug report or review note rather than a test plan:

- Lead with the exact false user-visible behavior or violated
  invariant.
- Anchor the report with the real test oracle: which object or durable
  state proves the incident.
- Include the nearest false-positive boundary, not just the positive
  repro.
- For orchestration and recovery bugs, state the execution
  interleaving and which owner each assertion is proving.
- If the existing test was blind, say exactly what it inspected and why
  that oracle was insufficient.
- Make acceptance criteria name the exact repro and the adjacent case
  that must stay green.

## Completion Bar

For each core axis touched by the change, ensure at least the dangerous
intersections are covered. Do not stop at one happy path or one
confirming test.
