# ADR 0001: Control-Plane Capability Architecture

## Status

Accepted

## Context

Registry control-plane concerns are currently spread across channel,
worker, and workflow code. Telegram egress, progress, delegation,
finalization, and worker timeline paths all know about registry
runtime presence, registry client construction, or registry-specific
fallback helpers.

That shape violates the repo's architecture rules:

- orchestration should import ports, not concrete backends
- one concern should have one path, not parallel runtime-backed and
  state-backed variants
- durable infrastructure must follow the existing backend/parity seams
- startup owns composition; channel runtimes should not hold backend-
  specific collaborators

It also blocks future control-plane implementations because every new
channel or admin surface would inherit registry-specific coupling.

## Decision

We will replace registry-shaped orchestration seams with a generic
control-plane capability architecture.

### 1. Capability ports, not registry-shaped ports

Consumers depend on capability ports named by domain behavior:

- `ConversationProjectionPort`
- `TaskRoutingPort`
- `AgentDirectoryPort`
- `HealthPublicationPort`

Registry is one implementation of those capabilities. Consumer code
must not depend on `RegistryRuntime`, `AgentRegistryClient`, or
registry-specific helper functions.

### 2. Durable control-plane bus

Workers and channel/workflow code will no longer make direct external
control-plane HTTP calls. They will express intent through a durable
command/reply bus. Processors that own live backends will claim,
execute, and complete those commands.

The bus is a first-class storage subsystem, not an ad hoc helper. It
must follow the same store-parity discipline as the transport facade:

- SQLite + Postgres implementations
- backend selection through `runtime_backend`
- schema migration when needed
- contract tests across both backends

### 3. Channel-neutral services container

Channel runtimes receive `BotServices`, which nests
`ControlPlaneServices`. No channel runtime holds registry-specific
fields such as `registry_runtime`, `registry_client_factory`, or
`registry_client_for_registry`.

Startup composition remains concrete and is allowed to know about the
current registry implementation. Consumer/orchestration code must only
see ports and service containers.

### 4. Persisted registry state is internal

Persisted registry connection state remains necessary, but it is an
implementation detail of registry-owned components. Channel, worker,
and workflow code must not branch on "runtime-backed" versus
"state-backed" behavior or construct registry clients from state.

## Consequences

### Positive

- removes concrete registry branching from orchestration code
- provides one control-plane path per concern
- keeps startup as the composition root while keeping consumers backend-
  neutral
- supports future control-plane implementations without reshaping
  channel runtimes
- makes shared-worker behavior depend on one durable contract instead
  of scattered helper fallbacks

### Costs

- introduces a substantial migration across ports, runtime wiring, and
  durable storage
- requires new typed command/reply models and new contract tests
- requires explicit lease/retry/idempotency handling in the new bus

### Guardrails

- extend existing seams before adding new modules
- add protocols before implementations
- keep backend selection inside `runtime_backend`
- do not add direct registry client access back into channel/workflow
  code during the migration
