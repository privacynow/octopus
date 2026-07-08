# SDK Bot Development Guide

This guide is for developers extending the current Python SDK/runtime and bot
platform in this repo.

The Java rebuild plan is separate planning material. This guide describes the
current shipped codebase.

## Code Areas

| Area | Purpose |
| --- | --- |
| `octopus_sdk/` | Shared contracts, workflow logic, protocol models/engine, registry client, runtime ports. |
| `app/` | Bot runtime, Telegram channel, provider integration, local DB state, deployment CLI. |
| `octopus_registry/` | Registry FastAPI app, registry store, protocol store/runtime, UI assets. |

Rules:

- shared behavior belongs in `octopus_sdk/`
- registry and Telegram are clients over shared rules
- do not create a second lifecycle/validation path in UI or Telegram
- do not create a second skill model
- do not create a second protocol runtime model
- do not create direct DB shortcuts as proof of product behavior

## Runtime Shape

An Octopus bot is composed from:

- provider integration
- transport/channel
- session runtime
- work queue
- shared workflows
- registry participant implementation
- skill/guidance runtime composition

Use [ARCHITECTURE.md](ARCHITECTURE.md) for the full system view.

## Where To Extend

### Shared workflow behavior

Start in:

- `octopus_sdk/workflows/`
- `octopus_sdk/registry/`
- `octopus_sdk/bot_runtime.py`

Examples:

- skill lifecycle rules
- guidance preview/composition rules
- routing decisions
- conversation workflow logic
- protocol list/start/status/actions/artifacts/export behavior
- Auto Protocol records, compilation, validation handoff, review policy,
  primary-artifact metadata, and transport-neutral render summaries

### Protocol behavior

Start in:

- `octopus_sdk/protocols/`
- `octopus_registry/protocol_store.py`
- `octopus_registry/protocol_http.py`
- `octopus_registry/protocol_runtime.py`

Rules:

- protocol state decisions live in SDK protocol engine/model code
- auto-generated protocols compile into canonical protocol documents in the SDK
- registry owns protocol persistence and API
- provider-backed Auto Protocol planning runs in bot runtime through hidden
  `auto_design` routed tasks; management-channel `design_auto_protocol`
  requests are rejected
- Telegram and UI call shared protocol service paths
- stage execution uses routed work/task paths
- artifact observations must feed the canonical run state

### Bot runtime/provider behavior

Start in:

- `app/runtime/`
- `app/providers/`
- `app/channels/`
- `app/db/`

Examples:

- provider request/response handling
- Telegram command handling
- registry delivery transport
- runtime session state
- work queue behavior

### Registry service/UI behavior

Start in:

- `octopus_registry/server.py`
- `octopus_registry/store_postgres.py`
- `octopus_registry/store_shared/`
- `octopus_registry/ui/js/components/`
- `octopus_registry/ui/js/helpers/`
- `octopus_registry/ui/css/main.css`

Rules:

- UI should use shared helpers/primitives before creating new ones
- UI must not invent its own protocol/skill/guidance state machine
- route changes must update docs and OpenAPI where applicable
- artifact actions should use shared artifact helpers
- runnable artifact actions should use the SDK/management runtime contracts:
  Registry persists lifecycle state and user-facing URLs, while
  `app/runtime/artifact_runtime.py` starts, stops, health-checks, logs, and
  proxies HTTP from inside the bot runtime

## Skills

The UI label is `Skills`; runtime code still says `skills`.

When extending:

- keep backend validation authoritative
- keep registry and Telegram as peer clients
- keep generated entries filterable
- keep routing skill derivation separate from conversation activation

Use:

- [USER_GUIDE.md](USER_GUIDE.md)
- [SKILLS_MODEL.md](SKILLS_MODEL.md)

## Guidance

Guidance is provider baseline policy, not a skill.

When extending:

- keep preview and runtime composition aligned
- make published guidance affect live runs
- keep lifecycle permissions consistent across registry and Telegram

## Protocols

Protocols are registry-owned workflow definitions/runs exposed to channels
through SDK service paths.

When extending:

- do not put protocol state rules in Telegram
- do not put protocol state rules only in browser JS
- keep standard/operator authoring separation enforced in backend and UI
- update `docs/PROTOCOL_ASSIGNMENT_AUDIT.md` if assignment behavior changes

## Local Development

Common workflow:

```bash
./octopus
./octopus status
./octopus logs <target> --follow
./octopus shell <target>
./octopus doctor <bot>
```

Default local deployment:

- registry stack has its own Postgres
- each bot stack has its own Postgres
- bot and registry connect through registry enrollment/heartbeat/delivery

When debugging state issues, check the effective `OCTOPUS_DATABASE_URL` inside
the live container before changing logic.

## Testing

Use the smallest test layer that proves the invariant, then add product-flow
coverage for cross-surface behavior.

Typical areas:

- SDK workflow tests
- registry service/API tests
- protocol engine/store/runtime tests
- Telegram command tests
- UI contract tests
- Playwright registry UI flows
- live registry smoke tests

Database inspection is allowed for diagnosis. It is not a substitute for
testing UI/API/Telegram behavior.

## Documentation Rule

If behavior changes, update the relevant guide in the same change.
