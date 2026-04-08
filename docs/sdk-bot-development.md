# SDK Bot Development Guide

This guide is for developers building or extending bots on top of the Octopus
SDK.

## What Lives Where

The repo has three main code areas:

- `octopus_sdk/`
  shared contracts, workflows, registry protocol, composition seams
- `app/`
  shipped Telegram bot runtime, provider integrations, deployment CLI
- `octopus_registry/`
  registry service and browser UI

The important rule is:

- shared behavior belongs in the SDK
- product clients call shared workflows
- do not duplicate business logic in the registry UI or Telegram layer

## Runtime Shape

An Octopus bot is composed from:

- provider integration
- transport(s)
- session runtime
- work queue
- shared workflows
- registry participant implementation

Use [ARCHITECTURE.md](ARCHITECTURE.md)
for the full system view.

## Development Principles

When adding behavior:

- put shared rules in `octopus_sdk/`
- keep registry and Telegram as thin wrappers over those rules
- do not create a second lifecycle or validation path
- do not create a second skill model
- do not create a second guidance model

The current product model assumes:

- skills are the primary capability concept
- routing is skill-derived
- guidance is provider policy

## Where To Extend

### New shared workflow behavior

Start in:

- `octopus_sdk/workflows/`
- `octopus_sdk/registry/`
- `octopus_sdk/bot_runtime.py`

Examples:

- skill lifecycle rules
- guidance preview rules
- routing decisions
- conversation workflow logic

### Bot runtime or provider behavior

Start in:

- `app/runtime/`
- `app/providers/`
- `app/channels/`

Examples:

- transport behavior
- provider integration
- startup and deployment wiring

### Registry UI or registry service behavior

Start in:

- `octopus_registry/`

Examples:

- browser workflows
- registry API handlers
- cache/invalidation behavior
- operator presentation

## Skills

If you are extending skills:

- keep the shared model in the SDK
- keep validation backend-owned
- keep file policy backend-owned
- treat registry and chat as peer clients

For practical skills behavior, use
[skills-guide.md](skills-guide.md).

For the lower-level model, use
[skills-model.md](skills-model.md).

## Guidance

Guidance is not a skill.

It is provider-scoped baseline policy.

If you extend guidance:

- keep runtime composition and preview aligned
- ensure published guidance actually affects live runs
- keep registry and Telegram on the same backend operations

## Local Development

For the normal local workflow:

```bash
./octopus
./octopus status
./octopus logs <target> --follow
./octopus shell <target>
./octopus doctor <bot>
```

For the shipped local deployment:

- the registry runs in its own stack
- each bot runs in its own stack
- each stack has its own Postgres container

This matters because cross-stack wiring bugs can look like runtime logic bugs.
When debugging connectivity or state corruption, confirm the effective
`OCTOPUS_DATABASE_URL` inside the live container before changing code.

## Testing

Prefer focused tests around the layer you changed.

Typical areas:

- SDK workflow tests for shared logic
- registry service tests for API behavior
- CLI manager tests for deploy wiring
- UI contract tests for browser surface changes

If you change deploy or compose wiring, add a regression test that protects the
actual invariant you need.

## Recommended Reading

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [skills-model.md](skills-model.md)
