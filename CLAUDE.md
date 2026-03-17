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
- **Transport facade parity rule.** Every new method added to
  `app/work_queue.py` must land in the same commit as: (a) a
  `work_queue_postgres_impl.py` conn-based implementation, (b) a
  `PostgresTransportStore` wrapper in `work_queue_postgres.py`, (c) a
  Postgres migration if the method touches a new table, and (d) a
  contract test case in `tests/contracts/test_transport_store_contract.py`.
  If Postgres support is genuinely impossible in the same slice, do not
  add the method to the facade or `__all__` until it is — a SQLite-only
  shortcut in the facade is not acceptable.
- **Storage layer boundary rule.** `app/access.py` and every other
  leaf/policy module must not import `sqlite3`, `work_queue`, or
  `runtime_backend`. Storage lookups belong at the handler integration
  point (e.g., `is_allowed()` in `telegram_handlers.py`), not in
  policy helpers that are supposed to be backend-neutral.
- **Registry store parity rule.** After M10H-2 lands, every new method
  added to `app/registry_service/store_base.py` must land in the same
  commit as: (a) a `RegistrySQLiteStore` implementation in `store.py`,
  (b) a `RegistryPostgresStore` implementation in `store_postgres.py`,
  (c) a Postgres migration in `app/db/migrations/postgres/` if the
  method touches a new table, and (d) a contract test case in
  `tests/contracts/test_registry_store_contract.py`. Until M10H-2 is
  complete, every new registry DB method must be labelled explicitly as
  "SQLite-only debt" in the commit message and a plan entry must exist
  for the Postgres equivalent. Saying "we fixed parity" without
  qualifying which seam is not acceptable.
- **Parity scope discipline.** "Postgres parity" is always scoped to a
  named seam: bot runtime transport store, bot runtime session store,
  registry store. Never say parity is fixed "across the board" or
  "system-wide" unless every named seam has a Postgres implementation,
  a backend selector, and a passing parameterized contract test.
  Fixing one seam while another remains SQLite-only is not parity — it
  is one seam fixed.
- **Extend before inventing.** Before adding a new module, function, or
  abstraction, find the existing seam that already owns that concern.
  Extend it. If no seam exists, create an interface/protocol first,
  then implement it — never add a concrete-only class that bypasses an
  existing abstraction boundary. A third copy-paste implementation is a
  signal that the abstraction is missing; fix the abstraction, do not
  add the copy.
- **Interfaces before implementations.** Every new pluggable component
  (store backend, surface adapter, provider, ingress handler) must have
  a Protocol or ABC defined before the first concrete implementation
  lands. The protocol lives in its own file (e.g. `store_base.py`,
  `ports.py`). Concrete implementations import and satisfy the protocol.
  Orchestration code imports only the protocol, never the concrete class.
- **No hand-rolled infrastructure.** Use battle-tested libraries for
  concerns that are not unique to this project: `psycopg` for Postgres
  connections, `psycopg_pool` for pooling, `pydantic` for request
  validation, `python-statemachine` for FSMs, `starlette` sessions for
  auth. Do not implement connection pools, JSON schema validators, state
  machines, or session middleware from scratch.
- **No parallel paths for the same concern.** If the transport store
  already owns work-item persistence, new ingress paths (webhook,
  registry delivery, future Slack adapter) must write through the same
  transport facade — not a second queue, a second table, or a second
  state machine. If the existing facade is insufficient, extend it.
- **Migration fidelity rule.** Versioned schema migrations are
  historical replay steps, not normal code. Each migration must
  reference column and table names as they existed at that version, not
  as they exist in the current schema. Rewriting historical migrations
  to use current names breaks upgrade paths from older databases.
  Fresh-install schemas (`_CREATE_SQL`, initial SQL files) describe the
  current version; migrations describe the delta from one version to
  the next.
- **Transport contract changes require full blast-radius audit.** When
  changing a transport facade return type or status value (e.g.
  `"busy"` → `"queued"`), grep the entire codebase for every consumer
  of that status before starting implementation. Surface call sites
  (Telegram handlers, registry bridge, registry delivery, tests) all
  encode the old contract. Change the transport implementation and
  every consumer in the same commit or coordinated sequence — never
  leave a half-migrated contract where some callers expect the old
  status and others the new one.
- **Stale-claim detection is age-based, not worker-based.** A claimed
  item is stale only when `claimed_at + lease_ttl < now`. Never treat
  `worker_id != current_worker_id` as evidence of staleness — in
  multi-worker deployments every other worker's live claims would be
  incorrectly recovered. The optimistic update guard
  (`WHERE worker_id = ? AND claimed_at = ?`) uses the stale row's
  original values for race protection, not for staleness detection.
- **Queue is a product contract, not a fallback.** If this repo says a
  surface or runtime path is queued, the transport store must durably
  accept and enqueue the work item. Do not simulate queueing with
  terminal `chat_busy`, `retry_later`, or other reject-and-redeliver
  behavior. When changing fresh-message admission from reject to queue,
  update the transport store, Telegram/registry call sites, and all
  tests in the same slice.
- **FSM and invariant review come before transport-store rewrites.**
  Any change to durable queueing, stale-claim recovery, replay, or
  admission policy must start with an audit of the existing
  `python-statemachine` transport workflow and its tests. Confirm the
  machine still expresses the intended contract (e.g. multiple queued
  fresh items, one claimed item per conversation, replay-only stale
  recovery). If the contract is missing, extend the workflow abstraction
  and tests first; do not patch around it with ad hoc SQL branches.
- **Recovered claimed work is replay-notice only.** Stale claimed work
  must never auto-rerun on recovery. Recovery transitions should move
  the item into the existing replay/discard flow (`dispatch_mode =
  'recovery'` → `pending_recovery`) so the user explicitly chooses what
  happens next. Automatic continuation risks circular loops and false
  actions after restart.
