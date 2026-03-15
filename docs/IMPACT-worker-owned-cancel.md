# Impact: Worker-owned execution and live cancel

## Contract(s) changed

- **Live execution owner**: Fresh plain-message execution and approval
  preflight are worker-owned. Telegram handlers admit work and return quickly.
  Some callback-driven follow-up execution paths still use the same
  provider/result contracts inline today.
- **Cancel semantics**: `/cancel` has two worker-era fast paths:
  - signal the worker-owned live run via `_LIVE_CANCEL`
  - cancel an admitted-but-not-yet-running queued fresh item through the
    durable queue
  No cutoff/pending state; no PTB concurrency hacks.
- **One fresh runnable item per chat**: Fresh provider-starting messages are
  admitted durably. If the queue already has fresh `queued` or `claimed` work
  for the chat, the next message is rejected/coalesced instead of becoming a
  second runnable run.
- **Credential setup ownership**: Credential-setup replies are recorded for
  dedupe only and handled inline; they do not create provider work items and
  never reach the worker/provider path as ordinary prompts.

## Authoritative owner of live execution

- **Worker loop** (`app/worker.worker_loop`): Claims work items, calls `worker_dispatch`.
- **worker_dispatch** (`app/telegram_handlers.worker_dispatch`): For fresh
  `InboundMessage` items, creates cancel event, registers it, runs
  `execute_request` or `request_approval`, unregisters.
- **execute_request / request_approval**: No longer called from
  `handle_message` for the normal fresh-message provider path; they are called
  from the worker path and, for now, from some approval/retry/replay callback
  paths that still need later worker-path consolidation.

## Entry points that currently start provider work

- `handle_message`: **Changed** — session/setup check happens before fresh
  admission; credential replies use `record_update()` only and stay inline.
  Ordinary fresh messages use `record_and_admit_message()` and return; they do
  not call `execute_request()` / `request_approval()`.
- Approval preflight (plain message with approval_mode): **Moved to worker** — worker runs `request_approval`.
- Approve button: Still calls `approve_pending` → `execute_request` inline (future: enqueue “execute after approval” for worker).
- Retry callback: Still inline (future: enqueue for worker).
- Recovery replay: Still inline (future: enqueue for worker).

## Fresh vs recovered work

- **Fresh**: Item was enqueued with `worker_id=None` and claimed by the worker in this run. Worker runs the provider.
- **Recovered**: Item was claimed by a previous process and requeued by
  `recover_stale_claims` with durable `dispatch_mode='recovery'`. Worker sends
  recovery notice instead of running the provider.

## Additional delivered hardening

- **Postgres anti-fan-out**: Fresh admission for the same chat is serialized
  per transaction with a per-chat advisory lock before checking/inserting
  fresh runnable work.
- **Queued fresh cancel**: `/cancel` can terminate an admitted-but-not-yet-
  running fresh queued item through `cancel_queued_fresh_for_chat()`.

## Proof-hardening and transport port (delivered)

- **Credential owner suite**: All credential tests that expect provider
  execution after `handle_message()` use `drain_one_worker_item()` or
  `running_worker()`; no stale inline-execution assumptions remain.
- **Queued-cancel durable state**: Backend-neutral contract test
  `test_cancel_queued_fresh_for_chat_terminal_state` and Postgres regression
  `test_cancel_queued_fresh_for_chat_terminal_state_postgres` assert terminal
  `failed`/`cancelled` and no runnable rows.
- **Stale comments**: `_LIVE_CANCEL` and `app/worker.py` module docstring
  updated to describe worker-owned model only.
- **Transport core**: `app/transports/types.py` and `ports.py` define
  InboundEnvelope, ConversationIO, EditableMessageHandle, TransportCapabilities.
- **Telegram adapter**: Outbound behind ConversationIO; `_BotMessage` replaced
  by Telegram adapter in handler/worker paths.
- **Simulator**: Handler-level harness in `tests/support/conversation_simulator.py`
  — inject via handle_message/cmd_* directly; run worker; one ordered output log
  (reply_text, edit_text, chat.send_message, reply_photo/reply_document, bot
  send_message/send_photo/send_document and edits, callback answer, callback
  edit_message_text; markup-only edits not included); wait
  conditions. No transport-level InboundEnvelope ingress or callback injection yet.
- **Canonical E2E**: `tests/test_simulator_e2e.py` — message→cancel (exact
  two-item durable shape), cancel before claim, second message busy (zero
  runnable, exact chat_busy item), credential off-queue, recovery notice.

## Tests to add/update

- One live run per chat: under message spam, provider is called only once.
- `/cancel` works while worker-owned execution is active (no PTB update concurrency).
- `/cancel` before worker claim leaves the admitted item in terminal
  `failed/cancelled` state and provider call count stays 0.
- Second plain message during a live run gets busy and never reaches provider;
  provider call count stays 1.
- Postgres concurrent admission is proven with two real connections for the
  same chat.
- Credential setup is proven off-queue while a real background worker is
  running.
- No test should use `processor.process_update(..., handler(...))` to simulate real Telegram concurrency.
- Approval/preflight cancel on worker path.
- Recovered items get recovery notice, not live execution.
