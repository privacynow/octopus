# telegram-agent-bot: Claude Project Rules

This supplements [docs/CLAUDE-global.md](/home/tinker/telegram-agent-bot/docs/CLAUDE-global.md)
with repo-specific failure patterns and workflows.

## Use These Local Skills

For high-risk work, open the matching local skill before changing code:

- `docs/codex-skills/contract-change-audit/SKILL.md`
- `docs/codex-skills/durable-state-hardening/SKILL.md`
- `docs/codex-skills/invariant-test-builder/SKILL.md`
- `docs/codex-skills/progress-ux-audit/SKILL.md`

## Bug Classes From Project History

These patterns caused repeated bugs. Check them on every nontrivial
change.

1. **Parallel path drift.** One path gets fixed, another stays stale:
   command vs callback, normal vs approval/retry, decorated handlers
   vs special cases.
2. **Raw state instead of resolved state.** `session.active_skills`
   instead of the resolved list, `cfg.working_dir` instead of
   `resolved.working_dir`, raw session/config in safety-sensitive or
   user-visible paths.
3. **Test doubles not matching production shape.** Fakes that omit
   public fields or methods production code reads.
4. **Testing implementation instead of contracts.** Tests that only
   prove "the code does what I wrote" instead of "all entry points obey
   the invariant."
5. **Component isolation hiding interaction bugs.** Heartbeat alone,
   provider progress alone, transport alone — but not the interaction.
6. **Subprocess and resource leaks.** Spawn without kill+wait, leaked
   SQLite handles, leaked descriptors on error paths.
7. **Decorator/wrapper swallowing handler behavior.** Eager callback
   answers, `finally` marking work `done` when success and failure
   should differ.
8. **Leaking internals to users.** Provider names, thread IDs, session
   IDs, internal terminology, raw provider errors.
9. **State-transition accounting failures.** Work marked `done` when it
   should be `failed` or replayable. Early returns skipping cleanup.
10. **Recovery loop.** A fix in replay/recovery can create an infinite
    loop if the recovery path itself re-enters the same durable state
    after interruption. Any change to replay, recovery, or claimed-item
    handling must be tested across four cases: interrupted original run,
    interrupted replay, failed replay, successful replay.
11. **Completion-owner drift.** In this repo, handler code,
    `_chat_lock`, `worker_dispatch()`, and `worker_loop()` all
    participate in work-item completion. Any change to completion
    semantics must include an explicit owner table: who marks `done`,
    who marks `failed`, who marks `claimed`, and what happens when the
    owner is interrupted.
12. **Ambiguous provider error signals.** Codex and Claude do not
    expose equally specific failure signals. Provider-specific reset
    behavior (clearing `thread_id`, resetting `started`) must be
    justified from the provider's error contract, not inferred from
    `rc != 0`. A generic error on a resumed run does not prove the
    resume itself is broken; it may be a transient failure on a healthy
    session.
13. **Telegram message-chain test blindness.** `reply_text()` returns
    a new status message; `TelegramProgress.edit_text()` lands on that
    returned object. Tests that inspect only `msg.replies` on the
    original message are blind to status edits. Use
    `_StickyReplyMessage` (or equivalent) when testing flows that
    create a status message and then update it via progress.
14. **State-transition bypass.** A new helper that transitions durable
    state (e.g. `reclaim_for_replay`) may bypass invariants enforced
    by the existing transition helpers (e.g. `claim_next_any`'s
    per-chat serialization check). Every new state-transition function
    must be audited against the full set of invariants on the table it
    modifies — not just the invariant the new path is about.
15. **Test boundary mismatch.** Testing `worker_dispatch()` directly
    when `worker_loop()` owns finalization. The test proved the
    function's return value was correct but was blind to what the
    caller does with it. Integration tests for completion semantics
    must exercise through the real ownership boundary, not one layer
    below it.

## Repo-Specific Process

- Ingress parity checklist for this repo: message, command, callback,
  admin, CLI, approval, retry.
- Provider-neutral language in all user-facing text: no provider names,
  no internal IDs, no implementation terminology.
- For durable workflows, specify possible states, who transitions them,
  what happens on failure, early return, and cancellation.
- **Urgent mitigation vs full fix.** If production pressure forces a
  mitigation, label it explicitly as mitigation, define what contract
  remains unresolved, and do not close the original bug until the
  unresolved contract has its own repro and test.
- Update the status doc only after the code and tests confirm runtime
  behavior.
