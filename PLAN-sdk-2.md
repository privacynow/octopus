# Plan: Unified SDK Transport, Registry Participation, and Conformance

## Purpose

This plan defines the target-state architecture for the bot runtime SDK and
for our concrete implementation scope.

The goal is not another partial extraction.

The goal is:

- one SDK-owned runtime model
- one SDK-owned transport abstraction that includes both ingress and egress
- one SDK-owned registry-participant abstraction
- one SDK-owned registry-authority abstraction
- Telegram and registry implemented as exact realizations of those interfaces
- a certification system that proves conformance

This plan replaces any prior framing that tolerated:

- separate ingress and egress concepts
- transport-specific coordination logic
- startup-snapshot identity gates
- app-owned fallback behavior
- partial parity
- "mostly unified" state

There is no intermediate target.

Our concrete implementation scope for this plan is:

- the Telegram bot/runtime implementation
- the registry server/authority infrastructure implementation

Both must end in target state.

## Required outcome

After this work:

1. A new bot transport, such as Slack, can be built by implementing SDK
   interfaces only.
2. Our Telegram implementation must implement:
   - the full primary transport interface
   - the full registry participant interface
3. Our registry server/authority implementation must implement:
   - the full registry authority interface set
4. Registry client-side participation in the control plane must be an SDK
   interface, not app-owned glue.
5. Registry server-side authority behavior must be expressed as SDK authority
   interfaces and implemented without app-local semantic drift.
6. Telegram and registry runtime behavior must be certified against the same
   SDK conformance suite.

## Problem statement

The current architecture is still split across too many ownership seams.

What is already good:

- shared wire models largely live in `octopus_sdk`
- task protocol and selector parsing are SDK-owned
- event sink, task routing, conversation projection, and discovery have SDK
  ports
- runtime admission types are SDK-owned

What is still wrong:

- the SDK channel abstraction is too thin
- ingress and egress are not one transport abstraction in practice
- registry inbound does not fit the same channel model as Telegram inbound
- Telegram still owns coordination behavior that should be SDK-owned
- registry participation is not modeled as a first-class cross-cutting bot
  capability
- server-side registry authority behavior is not cleanly expressed as SDK
  interface implementations
- conformance is not enforced by shared certification tests

This is why parity bugs keep surfacing.

## Full context from the audit and discussion

### What the code currently does

The code today effectively has three concerns, but they are not modeled cleanly
enough:

1. Primary user-facing transport behavior
   - Telegram today
   - Slack in the future
   - registry conversation transport for registry-only bots if desired

2. Registry participation behavior
   - enroll in registry control plane
   - publish health
   - discover agents
   - mirror conversations
   - submit typed coordination actions
   - route tasks
   - receive routed results

3. Registry authority/server behavior
   - backend/store/API/UI
   - control-plane processing
   - multi-authority mirroring
   - persistence and routing

The current codebase knows these concerns exist, but the ownership is muddled:

- Telegram transport is a `ChannelBootstrap`
- registry conversation/task egress are channels
- registry inbound is polling plus bridge admission, not a peer channel ingress
- Telegram delegation/direct-assignment logic still lives in
  `app/channels/telegram/delegation_channel.py`
- conversation projection semantics are not clean because the bus adapter
  rewrites `target_agent_id`
- health summary is capability/configuration flavored, not live-enrollment
  flavored

### What we concluded

The right architecture is:

1. one SDK transport abstraction
   - local bot-side
   - includes ingress and egress together

2. one SDK registry participant abstraction
   - optional at SDK ecosystem level
   - mandatory for our Telegram implementation
   - shared across any primary transport

3. one SDK registry authority abstraction
   - server-side authority/backend/control-plane
   - implemented by registry server components

This means:

- Telegram is a primary transport implementation
- Slack will be a primary transport implementation
- registry conversation/task transport can be a primary transport
  implementation
- any of those may also implement full registry participation
- our Telegram runtime must implement both transport and registry-participant
  interfaces

### Important correction from our discussion

The word `optional` applies only to the SDK ecosystem, not to our Telegram bot
implementation.

For our implementation:

- registry participation is mandatory
- full control-plane enrollment is mandatory
- discovery, mirroring, coordination, and task routing are mandatory
- partial registry capability is not acceptable

For our registry server/authority implementation:

- full authority contract compliance is mandatory
- multi-authority behavior is mandatory
- mirrored create/publish/message/action semantics are mandatory
- partial authority implementation is not acceptable

Certification must enforce this.

## Hard decisions

These are fixed decisions, not options.

### 1. Ingress and egress are one abstraction

There will not be separate primary concepts for ingress and egress.

A transport implementation owns:

- inbound normalization
- inbound admission
- outbound delivery
- outbound editing
- actions/callbacks
- identity/binding
- progress/timeline
- recovery/replay semantics

If a behavior belongs to a transport runtime, it belongs to the transport
interface.

### 2. Registry participation is not "just another channel"

Registry participation is a cross-cutting bot capability layer.

It is not a substitute for primary transport.

A bot runtime composes:

- exactly one primary transport implementation
- optionally, at SDK level, one full registry participant implementation

For our Telegram implementation:

- both are required

### 3. Registry authority/server behavior is also interface-owned

The registry server is not "misc app code."

It is the implementation of the SDK authority/control-plane interfaces.

All authority-side behavior must be expressible through SDK authority
contracts.

### 4. No transport-specific coordination logic

Direct assignment, delegation proposal, delegation approval/cancel, authority
resolution, local enrolled identity lookup, and coordination conversation
acquisition must be SDK-owned behavior behind SDK interfaces.

Telegram must not own bespoke coordination semantics.

### 5. No snapshot configuration for live runtime decisions

Runtime coordination decisions must use live state.

Startup-loaded config may be used for:

- diagnostics
- boot warnings

It may not be used for:

- deciding whether coordination is available
- deciding which local agent identity owns an authority
- deciding whether the runtime is enrolled

### 6. No duplicate semantic paths

There is one way to do each thing:

- one transport admission path
- one coordination submission path
- one authority-resolution path
- one local enrolled-identity resolution path
- one routed task lifecycle path
- one projection/mirroring path

No alternative app-local side path is allowed to survive.

### 7. No backward-compatibility shims

There will be no dual import surfaces and no parallel abstraction stacks.

All moved concepts update in one pass.

No:

- old `app.*` contract modules re-exporting SDK types
- temporary alternate runtime builders
- "legacy Telegram path" and "new SDK path"

### 8. No defaults, no guessing, no fallback routing

The unified interfaces must require explicit identity and ownership.

There will be no:

- "first coordination registry wins"
- startup-snapshot fallback ids
- fake capability-only health summaries standing in for live state
- inferred authority ownership without explicit resolution

### 9. Multi-authority is part of the contract

Multi-authority behavior is not best effort.

The contract must explicitly define:

- mirrored conversation creation
- mirrored event publication
- mirrored message submission
- mirrored typed action submission
- deterministic IDs across authorities
- failure semantics when authorities disagree or fail

### 10. Conformance is mandatory

SDK interfaces are not considered complete unless they are backed by a
conformance suite that implementations must pass.

## Current architectural defects to remove

### 1. Thin channel contract

Current `octopus_sdk/channels.py` models:

- ref ownership
- egress building
- optional ingress runner

This is insufficient.

It does not model:

- admission
- recovery
- callback/action ownership
- identity/binding lifecycle
- transport capabilities as executable obligations

### 2. Callback soup execution runtime

Current `octopus_sdk/runtime.py` exposes a runtime builder that still depends
on many app-provided callbacks.

This is not a closed SDK runtime contract.

The SDK must own real runtime interfaces, not callback bundles.

### 3. Registry inbound not modeled as the same transport abstraction

Current registry inbound uses polling and bridge admission outside the channel
model.

That is a parity break.

Registry inbound and Telegram inbound must both be implementations of the same
transport contract.

### 4. Telegram-owned coordination logic

Current Telegram coordination logic still exists in transport-local files.

That is where stale enrollment gating and parity drift came from.

It must be removed from transport ownership and replaced by SDK-owned
coordination interfaces.

### 5. Slippery conversation projection semantics

Current `ConversationProjectionPort.create_conversation(...)` has semantics
that are muddied by adapter-side rewriting of identity.

The final authority interface must make identity semantics explicit and exact.

### 6. Descriptor/capability lies

If an implementation declares a capability, the capability must actually work.

There is no tolerance for:

- `supports_timeline=True` with no actual timeline projection
- `accepts_channel_input=True` with transport-specific bypass paths

### 7. Health summary not reflecting live runtime reality

Capability/configuration summaries and live enrollment/connectivity summaries
must not be conflated.

The unified model must distinguish them and expose live state correctly.

## Target SDK structure

This section defines the final ownership model.

### A. SDK transport interfaces

These are local bot-side interfaces.

Required concepts:

- `TransportImplementation`
  - owns descriptor
  - owns identity semantics
  - owns inbound admission
  - owns outbound delivery
  - owns action handling
  - owns binding and timeline hooks
  - owns recovery/replay hooks

- `TransportDescriptor`
  - transport type
  - trust tier
  - capabilities
  - whether it accepts interactive input
  - whether it supports timeline projection
  - whether it supports message editing
  - whether it supports action presentation

- `TransportIngress`
  - normalize raw platform input into SDK inbound envelopes
  - admit those envelopes through one transport-owned admission surface

- `TransportEgress`
  - send/edit/delete
  - send files/images
  - action acknowledgements
  - binding sync
  - recovery notices
  - progress updates

- `TransportIdentityResolver`
  - conversation key
  - actor key
  - external conversation ref
  - transport-side binding semantics

The current separate ingress/egress model is replaced by this unified transport
contract family.

### B. SDK registry participant interfaces

These are bot-side optional-at-SDK-level capabilities.

Required concepts:

- `RegistryParticipant`
  - enroll
  - reconnect
  - heartbeat/health publication
  - local enrolled identity resolution
  - authority-scoped identity resolution
  - control-plane availability state

- `RegistryConversationMirror`
  - get-or-create mirrored conversation
  - publish mirrored events
  - add mirrored message
  - submit mirrored typed action

- `RegistryCoordination`
  - direct assignment
  - delegation proposal
  - delegation approval
  - delegation cancel
  - routed task submission
  - routed task progress
  - routed task result

- `RegistryDiscovery`
  - search agents
  - resolve authority for target agent

- `RegistryParticipantHealth`
  - live enrollment state
  - live connectivity state
  - authority capability summary
  - current local enrolled ids

For our Telegram implementation, all of these are mandatory.

### C. SDK registry authority interfaces

These are server-side interfaces implemented by the registry authority.

Required concepts:

- `RegistryAuthorityConversationStore`
  - create/get conversation
  - add message
  - submit typed action
  - publish events

- `RegistryAuthorityTaskRouter`
  - submit routed task
  - update routed task
  - report routed result

- `RegistryAuthorityDirectory`
  - search agents
  - resolve target authority

- `RegistryAuthorityHealth`
  - accept health publication
  - expose live connectivity and capability summary

- `RegistryAuthorityMirror`
  - deterministic mirrored IDs
  - multi-authority mirroring contract
  - mirror consistency and retry behavior

Registry HTTP/store/backend code becomes implementations of these authority
interfaces.

### D. SDK runtime composition interfaces

These unify transport and registry participation into one executable runtime
model.

Required concepts:

- `BotRuntime`
  - owns one primary transport
  - owns zero or one registry participant
  - owns provider execution runtime
  - owns session/runtime services
  - owns recovery and cancellation

- `RuntimeExecution`
  - provider invocation
  - progress lifecycle
  - approvals/retries
  - event sink publication

- `RuntimeAdmission`
  - one authoritative admission path for all inbound work
  - same rules regardless of transport origin

The current callback-heavy builder is replaced by SDK-owned runtime
composition interfaces.

## Required implementation profiles

Certification is profile-based.

### Profile: primary transport

Required for any transport implementation:

- ingress normalization
- admission
- outbound send/edit/action support
- identity/binding correctness
- recovery/replay semantics
- progress/timeline semantics
- capability declarations that match real behavior

### Profile: registry participant full

Required for our Telegram implementation.

Must include:

- enrollment
- reconnect and live state persistence
- live authority-scoped local identity resolution
- mirrored conversation projection
- mirrored event publication
- mirrored message submission
- mirrored typed action submission
- discovery
- authority resolution
- routed task submit/update/result
- routed result intake
- multi-authority correctness
- health publication

There is no partial pass for our Telegram runtime.

### Profile: registry authority

Required for registry server/backend implementation.

Must include:

- authority conversation store
- authority task routing
- authority agent directory
- authority health publication handling
- multi-authority mirroring contract

For our implementation, this entire authority profile is mandatory.

## Implementation plan

## Phase 0: Freeze the target-state model

### Work

1. Define the final SDK interface families:
   - transport
   - registry participant
   - registry authority
   - runtime composition
2. Define exact ownership of every current app-owned behavior.
3. Define exact certification profiles and profile requirements.
4. Remove any plan ambiguity about optional vs mandatory behavior.

### Required outputs

- one SDK interface map
- one ownership map from current modules to final interfaces
- one certification profile matrix
- one runtime composition diagram

### Exit criteria

- every current runtime behavior is assigned to exactly one final interface
- no behavior is left "transport-specific for now"
- Telegram mandatory profiles are explicitly fixed
- registry authority responsibilities are explicitly fixed

## Phase 1: Replace the SDK channel/runtime abstraction

### Work

1. Replace the thin `Channel`/`ChannelBootstrap` model with unified transport
   interfaces that own ingress and egress together.
2. Replace callback-heavy execution wiring with SDK-owned runtime composition
   interfaces.
3. Move transport identity and admission ownership fully into the SDK runtime
   contract.

### Rules

- do not preserve the old abstraction alongside the new one
- do not wrap old callback surfaces with shims
- delete and rewrite where the structure is wrong

### Exit criteria

- there is one SDK transport abstraction
- there is no separate primary ingress/egress abstraction stack left
- runtime composition no longer depends on callback soup for transport
  semantics

## Phase 2: SDK-own registry participation

### Work

1. Create SDK-owned registry participant interfaces for:
   - enrollment
   - live local enrolled identity
   - health publication
   - agent discovery
   - authority resolution
   - mirrored conversation operations
   - coordination actions
   - task routing participation
2. Move Telegram-owned coordination logic into SDK-owned registry participant
   implementations.
3. Eliminate startup-config gating for live coordination decisions.

### Exit criteria

- there is no Telegram-local coordination policy layer left
- live registry participation decisions come from one SDK-owned interface
- direct assignment and delegation use the same shared registry participant
  surface
- no runtime path depends on `config.registry_agent_ids` for live decisions

## Phase 3: SDK-own registry authority interfaces

### Work

1. Define authority-side SDK interfaces for conversation projection, task
   routing, directory, health, and mirroring.
2. Refactor registry store/backend/control-plane code to implement those
   interfaces directly.
3. Make multi-authority behavior part of authority contract implementation,
   not adapter-local convention.

### Exit criteria

- registry server/backend behavior is expressed as authority interface
  implementations
- conversation projection semantics are exact and unambiguous
- multi-authority message/action/event mirroring is contract-owned

## Phase 4: Rebuild Telegram as a pure implementation

### Work

1. Refactor Telegram runtime to implement:
   - primary transport
   - full registry participant
2. Remove any transport-local coordination side paths.
3. Route all inbound coordination actions through the same durable admission
   and execution model.
4. Ensure descriptor-declared capabilities are actually implemented.

### Exit criteria

- Telegram runtime imports only SDK interfaces for transport and registry
  participation contracts
- no coordination logic remains stranded in Telegram-only files
- Telegram passes both:
  - primary transport profile
  - full registry participant profile

## Phase 5: Rebuild registry bot-side runtime as a pure implementation

### Work

1. Refactor registry delivery/bridge/runtime code so registry bot-side behavior
   is an implementation of:
   - primary transport when acting as registry conversation/task transport
   - registry participant where applicable
2. Remove the conceptual split between registry inbound bridge logic and
   channel semantics.

### Exit criteria

- registry bot-side runtime fits the same SDK transport/runtime model as
  Telegram
- no separate bridge-only semantic path remains outside the unified model

## Phase 6: Certification and compliance suite

### Work

Build one SDK-owned certification system with profile parameters.

Required suites:

1. Transport conformance
   - ingress normalization
   - admission
   - outbound send/edit/action
   - identity and binding
   - progress/timeline
   - recovery/replay

2. Registry participant conformance
   - enrollment
   - live identity resolution
   - discovery
   - authority resolution
   - mirrored conversation lifecycle
   - typed coordination action submission
   - routed task submit/update/result
   - routed result intake
   - health publication
   - multi-authority consistency

3. Registry authority conformance
   - conversation projection
   - message submission
   - typed action handling
   - task routing
   - directory
   - health handling
   - multi-authority mirror semantics

4. Telegram product profile
   - primary transport required
   - full registry participant required

5. Registry authority implementation profile
   - full registry authority required

### Required properties

- parameterized by required profile
- no partial pass for missing mandatory profile capability
- no implementation-specific waiver system
- our Telegram implementation must satisfy its full required profiles
- our registry authority implementation must satisfy its full required profile

### Exit criteria

- the SDK has a runnable certification suite
- Telegram cannot pass unless it satisfies both required profiles
- registry authority cannot pass unless it satisfies full authority profile

## Phase 7: Remove obsolete app-local abstractions

### Work

Delete any remaining app-local abstractions that duplicate or shadow SDK
contracts.

This includes:

- app-local contract modules
- transport-local coordination abstractions
- bridge-only semantic layers that should now be transport/runtime
  implementations
- startup snapshot identity behavior used for live decisions

### Exit criteria

- there is one abstraction stack
- no duplicate ownership remains
- no legacy code path can bypass the final SDK contract model

## Required file/module outcomes

This section is intentionally concrete.

### SDK must own

- transport interfaces
- registry participant interfaces
- registry authority interfaces
- runtime composition interfaces
- inbound envelope/admission contracts
- identity contracts
- task protocol
- registry wire models
- selector parsing
- conformance suite

### App may still own

- concrete Telegram implementation
- concrete registry authority/server implementation
- concrete provider implementations
- deployment/startup/process bootstrapping
- product UI/server wiring

But every one of those must be an implementation of an SDK interface.

## Verification plan

Verification is mandatory.

### Static verification

1. import graph checks
   - implementation code imports SDK contracts
   - SDK does not import `app.*`
2. duplicate-ownership checks
   - no duplicate contract surfaces remain
3. descriptor truth checks
   - declared capabilities match actual implementation coverage

### Unit and integration verification

1. SDK conformance suite
2. Telegram implementation profile suite
3. Registry authority profile suite
4. multi-authority deterministic id suite
5. admission/recovery parity suite across transport origins

### Operational verification

1. Telegram bot enrolled in registry can:
   - discover
   - delegate
   - mirror conversations
   - receive routed results
2. registry-only bot can participate through the same SDK contracts
3. mirrored operator actions behave identically regardless of transport origin

## Hard exit criteria

This plan is complete only when all of the following are true:

1. There is one SDK-owned transport abstraction that includes both ingress and
   egress semantics.
2. There is one SDK-owned registry participant abstraction.
3. There is one SDK-owned registry authority abstraction.
4. Telegram implements the SDK transport abstraction with no app-local
   semantic side path.
5. Telegram implements the full registry participant interface with no
   omissions.
6. Registry bot-side runtime implements the same SDK transport/runtime model as
   Telegram.
7. Registry server/backend implements the SDK authority interfaces.
8. No live runtime decision depends on startup-snapshot registry identity.
9. No transport-local coordination policy survives outside SDK-owned
   interfaces.
10. Multi-authority create/publish/message/action semantics are contract-owned
    and tested.
11. Capability declarations are truthful and enforced by tests.
12. The SDK includes a certification suite with profile parameters.
13. Telegram passes:
    - transport profile
    - full registry participant profile
14. Registry authority passes full authority profile.
15. There are no duplicate abstraction stacks, no compatibility shims, no
    fallback paths, and no parallel old/new interfaces.
16. A new transport implementation can be authored against the SDK without
    importing `app.*`.

## Non-goals

These are explicitly out of scope:

- preserving the old abstraction stack
- temporary compatibility layers
- partial registry support for our Telegram implementation
- "best effort" multi-authority semantics
- alternate code paths kept for safety
- renaming concepts without fixing ownership

## Final standard

The standard is simple:

everything is an implementation of an interface.

Not some things.

Everything.
