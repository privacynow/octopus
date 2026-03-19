# Architecture

AI coding assistant exposing Claude and Codex through Telegram and a
browser-based registry UI. Users send messages; the system executes provider
runs with skills, credentials, approval gates, and project bindings.

## Layers

```
┌───────────────────────────────────────────────────────┐
│                    Channels                           │
│   Telegram (PTB)              Registry (FastAPI)      │
│   ingress → presenters        http → ingress → ui     │
│   egress                      egress                  │
├───────────────────────────────────────────────────────┤
│                     Agents                            │
│   bridge ─ delivery ─ delegation ─ client ─ runtime   │
├───────────────────────────────────────────────────────┤
│                    Workflows                          │
│   execution    pending     recovery    delegation     │
│   conversation runtime_skills  provider_guidance      │
│   credentials  lifecycle_machine                      │
├───────────────────────────────────────────────────────┤
│                     Runtime                           │
│   composition ─ dispatch ─ work_admission             │
│   session_runtime ─ inbound_types                     │
├───────────────────────────────────────────────────────┤
│                 Domain Services                       │
│   skill_catalog ─ skill_activation ─ skill_import     │
│   provider_guidance ─ capability ─ credential         │
├───────────────────────────────────────────────────────┤
│                   Durable Stores                      │
│   content_store    credential_store    work_queue     │
│   session/storage  registry_service/store             │
│   (each: SQLite + Postgres + contract tests)          │
├───────────────────────────────────────────────────────┤
│              Ports, Types & Config                    │
│   ports/egress    providers/base    config            │
│   session_state   inbound_types    content_models     │
│   execution_context  skill_types  credential_types    │
└───────────────────────────────────────────────────────┘
```

Dependencies flow downward. No layer imports from a layer above it.
63 gate tests enforce this.

## Message Flow

```
User ──→ Telegram/Registry
              │
              ▼
         Normalize event
         (InboundEnvelope)
              │
              ▼
         Work Queue
         (admit → claim)
              │
              ▼
         Worker Dispatch
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
  Execute  Approve  Recover
  Request  Pending  Stale
     │        │        │
     ▼        ▼        ▼
  Provider  Session  Recovery
  Run       Gate     Machine
     │
     ▼
  Finalize
  (usage, timeline, delegation, webhook)
     │
     ▼
  Channel Egress
  (reply to user)
```

## Channels

Each channel owns: bootstrap, ingress, egress, presenters.

**Telegram** — PTB bot. `bootstrap.py` constructs `TelegramRuntime` (a
dataclass, not a singleton) and wires handlers. `ingress.py` normalizes
Telegram updates into `InboundEnvelope` and dispatches to workflows. All
keyboard/HTML rendering lives in `presenters.py`.

**Registry** — FastAPI HTTP service. `http.py` is a thin route boundary.
`ui.py` owns the browser shell. `egress.py` publishes timeline events back
to the registry.

Both channels converge at the workflow layer through the same ports.

## Workflows

Eight concern-owned packages under `app/workflows/`. Each has `contracts.py`
(Protocol ports + frozen dataclass outcomes) and an orchestrator.

Five workflows have explicit **decision machines** — pure functions that
take a frozen snapshot and return a frozen decision with effects:

```
decide(snapshot, action) → Decision(status, ok, effects)
```

| Machine | Concern | States |
|---|---|---|
| `lifecycle_machine` | Skill/guidance lifecycle | draft → review → published → archived |
| `pending/machine` | Approval/retry | none ↔ pending_approval ↔ pending_retry |
| `recovery/machine` | Transport recovery | queued → claimed → pending_recovery → done/failed |
| `runtime_skills/setup_machine` | Credential collection | start → advance → ready/cancel |
| `delegation/machine` | Multi-agent delegation | proposed → submitted → completed/cancelled |

Effects are applied atomically at the store boundary.

## Durable Stores

Five store seams. Each has an abstract base, SQLite and Postgres
implementations, and parameterized contract tests across both backends.

| Store | Owns |
|---|---|
| **content_store** | Skills, guidance, lifecycle, revisions, approvals |
| **credential_store** | Per-user skill credentials |
| **work_queue** | Work items, claims, recovery, usage, heartbeats |
| **session/storage** | Per-conversation session state |
| **registry_service/store** | Agent enrollment, deliveries, conversations, timeline |

Backend selected at startup: `database_url` set → Postgres, otherwise SQLite.

## Agents

Multi-agent registry integration. `bridge.py` creates registry clients and
publishes timeline events. `delivery.py` routes inbound registry deliveries
(`channel_input`, `routed_task`, `channel_action`) into the work queue.
`delegation.py` is a thin bridge over `workflows/delegation/`.

Agents have zero channel imports.

## Provider Port

`providers/base.py` defines the `Provider` protocol:

- `run(state, prompt, images, progress, context, cancel) → RunResult`
- `run_preflight(prompt, images, progress, context, cancel) → RunResult`

Implementations: `ClaudeProvider`, `CodexProvider`.

`runtime/dispatch.py` (136 lines) is pure provider-call plumbing — it receives
a `RuntimeDispatchRuntime` with injected callbacks and calls the provider.
Zero channel imports, zero workflow imports.

## Egress Port

`ports/egress.py` defines the `ChannelEgress` ABC:

- `send_text()`, `send_photo()`, `send_document()`
- `bind()`, `on_outcome()`, `send_recovery_notice()`
- `ChannelCapabilities` declares what the channel supports

Implementations: `TelegramChannelEgress`, `RegistryChannelEgress`.
`channel_egress_factory.py` selects implementation by conversation reference.

## Data Model

### Session State

Per-conversation JSON blob: provider config, active skills, role, approval
mode, compact mode, project binding, model profile, plus optional pending
states (approval, retry, setup, delegation).

### Work Items

```
queued → claimed → done | failed | pending_recovery
```

One claimed item per conversation (enforced by unique index). Stale claims
recovered by age-based sweep.

### Skill Lifecycle

```
draft → review → published → archived
              ↘ rejected → draft
```

Atomic transitions via `apply_skill_lifecycle_transition` inside `with conn:`.

### Delegation

```
proposed → submitted → completed | partial_failed
        → cancelled
```

Child tasks: proposed → queued → leased → running → submitted → completed | failed.

## Design Principles

1. **Channels are thin** — normalize, dispatch, render. No business logic.
2. **Workflows own domain logic** — one package per concern with typed ports.
3. **Dependency direction enforced** — channels → workflows → runtime → stores.
4. **Machines are pure functions** — snapshot in, decision out, effects applied atomically.
5. **Store parity required** — every method in both SQLite and Postgres.
6. **No singletons** — runtime state is an explicit dataclass instance.
7. **Collaborator injection** — modules receive dependencies as parameters.
