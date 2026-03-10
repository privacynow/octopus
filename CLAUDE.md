# telegram-agent-bot: Project-Specific Rules

This supplements the global engineering standards with patterns and
bug classes specific to this codebase.

## Bug Classes (from project history)

These patterns have caused bugs repeatedly. Check for them on every
change.

**1. Parallel path drift.** One handler path fixed, another left stale.
Command vs callback, normal vs approval/retry, decorated handlers vs
special cases like /help and /start.

**2. Raw state instead of resolved state.** `session.active_skills`
instead of the resolved list, `cfg.working_dir` instead of
`resolved.working_dir`, raw session in doctor instead of resolved context.

**3. Test doubles that don't match production shape.** `FakeProgress`
missing `last_update`, `FakeCallbackQuery` discarding answer payload,
`FakeMessage` ignoring `edit_message_reply_markup`.

**4. Testing implementation instead of contracts.** Tests that verify
"my code does what I coded" instead of "all entry points obey the same
invariant."

**5. Component isolation hiding interaction bugs.** Heartbeat tested
alone, provider progress tested alone, never together. The interaction
— two concurrent writers to the same message — is where the bug lives.
Core axes: trust x model, project x approval, progress x long output,
work items x interrupts x retries.

**6. Subprocess and resource leaks.** Processes spawned without
kill+wait on timeout, file descriptors leaked on schema errors, test
SQLite connections leaked.

**7. Decorator/wrapper swallowing per-handler behavior.** Eager
`query.answer()` before the handler could provide feedback. `finally`
marking work "done" even on exceptions. Use `except`/`else` instead of
`finally` when success/failure differs.

**8. Leaking internal implementation to users.** Provider names, thread
IDs, session IDs, "preflight" terminology, "context compaction," raw
error output. User-facing text must never contain these.

**9. State-transition accounting failures.** Work items marked "done"
when they should be "failed." Early returns skipping cleanup. For
durable workflows: specify possible states, who transitions them, what
happens on failure, early return, and cancellation.

**10. Recovery loop.** A fix in replay/recovery can create an infinite
loop if the recovery path itself re-enters the same durable state
after interruption. Any change to replay, recovery, or claimed-item
handling must be tested across four cases: interrupted original run,
interrupted replay, failed replay, successful replay.

**11. Completion-owner drift.** In this repo, handler code,
`_chat_lock`, `worker_dispatch()`, and `worker_loop()` all participate
in work-item completion. Any change to completion semantics must
include an explicit owner table: who marks `done`, who marks `failed`,
who marks `claimed`, and what happens when the owner is interrupted.

**12. Ambiguous provider error signals.** Codex and Claude do not
expose equally specific failure signals. Provider-specific reset
behavior (clearing `thread_id`, resetting `started`) must be justified
from the provider's error contract, not inferred from `rc != 0`. A
generic error on a resumed run does not prove the resume itself is
broken — it may be a transient failure on a healthy session.

**13. Telegram message-chain test blindness.** `reply_text()` returns
a new status message; `TelegramProgress.edit_text()` lands on that
returned object. Tests that inspect only `msg.replies` on the original
message are blind to status edits. Use `_StickyReplyMessage` (or
equivalent) when testing flows that create a status message and then
update it via progress.

## Repo-Specific Process

- Make changes one at a time, test each before moving on.
- Update the STATUS doc after each tested change.
- Ingress parity checklist for this repo: message, command, callback,
  admin, CLI, approval, retry.
- Provider-neutral language in all user-facing text: no provider names,
  no internal IDs, no implementation terminology.
- **Urgent mitigation vs full fix.** If production pressure forces a
  mitigation, label it explicitly as mitigation, define what contract
  remains unresolved, and do not close the original bug until the
  unresolved contract has its own repro and test.
