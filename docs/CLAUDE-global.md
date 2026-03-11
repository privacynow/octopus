# Engineering Standards for Claude

Fix contracts, not call sites. Audit equivalent paths before coding.
Test invariants, not just scenarios. Treat failure paths as first-class.
Use resolved context as the only authority.

## Core Principles

- **Build once, reuse everywhere.** Search for existing modules,
  dataclasses, builders, and workflows before writing new code.
- **Prefer battle-tested libraries** over hand-rolling equivalent
  functionality unless the dependency cost clearly outweighs the
  benefit.
- **One authoritative source per concept.** Cross-cutting concerns
  should have one owner. If a resolved context exists, use it. If no
  authoritative builder exists, create one before patching call sites.
- **Durable state owns correctness.** In-memory state is optimization,
  not authority. Recovery must come from durable state, not process
  memory.
- **Failure paths are normal.** Interrupts, timeouts, stale callbacks,
  duplicate delivery, and restarts are part of the runtime contract.
- **Rendering is product correctness.** User-visible progress, output
  shaping, and error presentation are architecture, not polish.
- **Use clean ASCII diagrams** instead of mermaid when a diagram is
  needed.

## Operating Procedure

### Before coding: contract-first preamble

For any nontrivial change, first write a short impact statement:

- **Contract being changed** — what interface or invariant is affected
- **Source of truth** — what owns the concept authoritatively
- **Affected entry points** — enumerate with `rg`, do not guess
- **State/persistence touched** — durable and in-memory state involved
- **Failure paths** — timeout, interrupt, stale callback, exception,
  duplicate delivery, restart-in-the-middle
- **Required invariants** — what must hold afterward across all paths
- **Tests to add** — invariant tests, not just scenario tests

If you cannot fill this out, you are not ready to code.

### During coding: parity and audit

1. **Enumerate all call sites with `rg` before editing.** Do not assume
   there are only one or two.
2. **Check equivalent ingress paths for parity.** Most bugs were
   "fixed in one path, broken in another."
3. **Audit raw vs resolved reads.** If resolved context exists, replace
   raw reads unless they are intentionally persistence-only.
4. **Ban ad-hoc recomputation.** Update the authoritative builder
   instead of reconstructing equivalent logic inline.
5. **Separate interacting bugs into separate contracts.** If analysis
   identifies N distinct failure modes, the plan must name N contracts,
   N fixes, and N independent verifications. "Interacting" is not
   permission to merge them into one test bucket.
6. **Trace the fix through a second failure.** For orchestration or
   durable-state changes, answer: "what if the new recovery path is
   also interrupted or fails?" If the answer creates a loop or leaves
   state poisoned, the fix is incomplete.
7. **Name the completion owner explicitly.** Any workflow with retries,
   replay, claims, or background workers must state: who marks success,
   who marks failure, who may swallow exceptions, and who must never
   finalize. If ownership changes, test the new owner's interruption
   path.
8. **Destructive resets require typed evidence.** Session reset, state
   invalidation, or fallback-to-fresh logic cannot key off a generic
   error unless the provider contract proves that error is specific
   enough. If the signal is ambiguous, the task is still a design
   problem, not ready for a fix.
9. **New state transitions must satisfy existing invariants.** When
   adding a function that writes to a shared table (e.g. work_items),
   audit it against every invariant the existing writers enforce. If
   `claim_next_any` enforces per-chat single-claimed, then
   `reclaim_for_replay` must enforce it too. The new path does not
   get an exemption just because it serves a different feature.
10. **Test through the real owner, not one layer below.** If
    `worker_loop` owns finalization after `worker_dispatch` returns,
    testing `worker_dispatch` alone proves nothing about what state
    the item ends up in. The test must exercise through the boundary
    that owns the outcome the user depends on.

### After coding: completion criteria

Work is not done until:

- All affected entry points are checked for parity
- Invariant tests are added or updated (not just scenario tests)
- The full relevant suite passes
- At least one direct repro confirms the fix
- At least one adjacent regression risk is tested

### Pre-merge gate (hard stop)

If any answer is missing or unclear, the change is not ready.

1. How many distinct failure contracts are being changed?
2. Who owns finalization on every exit path?
3. What happens if recovery is interrupted again?
4. What exact signal makes reset/invalidation safe?
5. What exact object or state does each test observe?
6. Which adjacent case proves the fix does not overfire?

## Testing

Test the contract at the real boundary, then test the nearest way it
could still be wrong.

### Three layers per nontrivial change

1. **Focused contract test** — proves the invariant directly.
2. **Entry-point integration test** — proves the contract survives
   real orchestration through the actual user-facing path.
3. **Adjacent regression test** — tests one nearby path likely to drift.

### Rules

- **Test the real boundary, not the helper.** If the bug is in the
  persistence layer, testing the serializer alone proves nothing.
- **Assert both visible output and persisted state.** Many bugs were
  one being wrong while the other looked fine.
- **Negative capability tests are high-value.** Prove that forbidden
  things cannot happen — often more valuable than another happy path.
- **Test doubles must match production shape.** Every public field and
  method that production code reads must exist on the fake.
- **Test infrastructure changes require production rigor.**
- **Every classification fix needs a false-positive test.** Not just
  "condition X triggers reset," but also "adjacent condition Y must
  not trigger reset." If the fix classifies errors, test the boundary.
- **Every user-visible test must declare its oracle.** State which
  object owns the rendered text: original message, returned status
  message, chat send buffer, or persisted state. If the test inspects
  a different object than the one the user sees, it is blind.

### Minimum completion bar

**Contract/orchestration:** 1 contract test, 1 entry-point integration
test, 1 adjacent parity test.

**Durable-state:** success, failure/interruption, duplicate/idempotency,
recovery/restart if state machine involved.

**UX/rendering:** visible output, edge formatting, "does not leak
internals," adjacent provider/path parity.

## Commit Discipline

- Never commit unless explicitly asked.
- Never add Claude's name to commit messages or as co-author.
- Never auto-commit.
- **Never publish secrets.** Before any commit, verify no passwords,
  API keys, tokens, or `.env` files are included. Verify `.env` is in
  `.gitignore`.

## Process

- "Analysis only" means no code changes, only discussion.
- Don't stop mid-plan unless blocked — finish all items.
