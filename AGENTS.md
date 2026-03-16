# telegram-agent-bot: Codex Project Rules

This supplements [docs/AGENTS-global.md](/home/tinker/telegram-agent-bot/docs/AGENTS-global.md)
with repo-specific failure patterns and workflows.

## Use These Local Skills

For high-risk work, open the matching local skill before changing code:

- `docs/codex-skills/contract-change-audit/SKILL.md`
- `docs/codex-skills/durable-state-hardening/SKILL.md`
- `docs/codex-skills/invariant-test-builder/SKILL.md`
- `docs/codex-skills/progress-ux-audit/SKILL.md`

## Pluggable Subsystem Architecture (Port + Factory Rule)

This repo has three categories of pluggable subsystem: **surface** (conversation
output transport), **storage** (session persistence), and **provider** (AI execution
engine). Every pluggable subsystem follows the same architectural pattern without
exception.

### The Rule

**No orchestration code names a specific surface, storage, or provider
implementation.** Orchestration code (worker_dispatch, delivery, handlers) imports
only abstract ports and calls only factory functions. It never imports
`TelegramConversationIO`, `RegistryConversationIO`, `SqliteSessionStore`, or any
other concrete class directly.

### Required Shape for Every Pluggable Subsystem

```
app/transports/ports.py          ← abstract port: ConversationIO / InteractionSurface
app/transports/telegram_adapter.py  ← concrete: TelegramConversationIO
app/transports/registry_adapter.py  ← concrete: RegistryConversationIO
app/transports/factory.py        ← factory: create_outbound_surface(conversation_ref, ...)
```

The factory is the single place that decides which implementation to construct.
Adding a new surface (iMessage, Slack, SMS) means adding a new adapter and a branch
inside the factory. The orchestration layer is not touched.

### How To Add a New Surface

1. Create `app/transports/<name>_adapter.py` implementing `InteractionSurface`.
2. Add a branch in `app/transports/factory.py:create_outbound_surface()`.
3. Add a branch in `app/transports/factory.py:trust_tier_for_source()` if the
   surface has distinct trust semantics.
4. Add factory tests: `test_factory_<name>_ref_produces_<name>_surface`.
5. Do not touch `worker_dispatch`, `delivery.py`, or any handler.

### Trust Tiers

Trust determination is a factory concern, not an orchestration concern.
`worker_dispatch` calls `factory.trust_tier_for_source(source, user, config=cfg)`.
`factory.py` delegates to `app/access.trust_tier(config, user)`. Inline `source`
string comparisons for trust do not belong in orchestration code — they belong in
the factory.

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
   prove “the code does what I wrote” instead of “all entry points obey
   the invariant.”
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
14. **Surface-specific logic in orchestration code.** `worker_dispatch`
    and delivery handlers must never import or branch on a specific
    surface adapter. If you add `if conversation_ref.startswith(...):`
    or `if source == "registry":` in an orchestration file, you have
    violated the port+factory rule. Put the branch in the factory.
15. **send_message bypassing send_text.** On `TelegramConversationIO`,
    `send_message()` must delegate to `send_text()` so that the
    `replies` list is populated and the returned handle is a
    `TelegramEditableMessageHandle`. Tests that call `send_message`
    and inspect `bot.messages` directly are blind to this bypass.
16. **Silent recovery notice failure.** A new surface that inherits the
    `InteractionSurface.send_recovery_notice()` no-op without overriding
    it will never inform users that interrupted work needs replay. Every
    surface with a user-facing UI channel must override it.

## Repo-Specific Bug Reports

When writing a bug report for this repo:

- Lead with the exact false user-visible behavior or violated durable
  contract.
- Anchor the report with `update_id`, `chat_id`, matching
  `journalctl` lines, and the relevant `updates` / `work_items` or
  `sessions` row state.
- For work-item and recovery bugs, state whether the item was fresh
  same-boot, stale claimed, `pending_recovery`, or true restart
  recovery, and prove that classification from durable state.
- Separate symptom, violated contract, root cause, scope,
  non-solutions, testing strategy, and acceptance criteria.
- If the bot told the user something false, say that explicitly.
- Name equivalent ingress paths that may share the same ownership or
  state-transition bug.

## Repo-Specific Process

- Recommend the strongest justified fix as the default path. Prefer the
  option that improves correctness, reliability, maintainability,
  performance, safety, or operator usability, even when it is harder.
  Do not present a weaker shortcut as equally valid unless the user
  explicitly asks for tradeoffs or the task is truly bounded to copy or
  docs.
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
