# Skills Model

Skills use one shared backend model across the registry UI, Telegram, and any
future clients. Different clients may bundle actions differently, but they must
call the same backend operations and arrive at the same state transitions.

## Core Layers

Every skill surface should describe the same bot/session states:

1. `Catalog`
   What skills exist for this product, tenant, or bot context.
2. `Available on this bot`
   Which skills are available on one specific agent.
3. `Default for new conversations`
   Which available skills seed newly created conversations for that bot.
4. `Active in this conversation`
   Which available skills are turned on for one conversation right now.

These states are distinct. Making a skill available on a bot does not activate
it in every conversation. Setting a default seeds new conversations only.
Activating a skill in one conversation does not change bot-wide availability.

## Routing Is Skill-Derived

Cross-bot discovery and delegation use `routing skills`, which are derived from
the normal skill state rather than managed as a second product object.

A routing skill is:

- available on the bot
- runtime-ready
- allowed by registry-owned routing policy

Routing uses that bot-level projection. Conversation activation stays
session-local. Additional filters such as region, tier, or compliance may
exist as routing policy dimensions, but they are not a second skill system.

## Orthogonal Dimensions

Skills also carry dimensions that are independent from the core states:

- `Source`
  - `Core`: built into the runtime image
  - `Store`: installed from the remote skill store
  - `Custom`: authored inside Octopus and managed through lifecycle actions
- `Setup`
  - `Needs setup`: requires credentials before it can be active in a
    conversation
  - `Ready`: no missing setup is blocking activation
- `Lifecycle`
  - `Draft`
  - `Submitted`
  - `Approved`
  - `Published`
  - `Archived`

## Shared Operations

The shared backend operations are:

- list or search catalog
- inspect one skill
- install, update, or uninstall a store skill on a bot
- activate, deactivate, or clear skills in a conversation
- start setup and submit credential values
- create, inspect, edit, submit, approve, reject, publish, or archive custom skills

Clients can compose these operations into smoother flows, but they should not
reimplement their rules or invent extra state machines.

Examples:

- Registry UI `Add to conversation`
  - inspect bot availability
  - activate
  - if setup is needed, prompt for credentials
- Telegram `/skills add <name>`
  - activate
  - if setup is needed, prompt for credentials

Both flows still use the same activation and setup operations.

## Peer Clients

Registry UI and chat clients are peers in product terms:

- same backend operations
- same validation
- same permissions
- same lifecycle
- same vocabulary

The registry UI is allowed to be a richer wrapper because it can present
multi-step flows, detail panels, and lifecycle history more comfortably than a
chat surface. That richer UX must still be built on the shared backend
operations.

## Draft Package Model

Custom skills use the same package shape as Core and Store skills. The mutable
draft model includes:

- metadata
  - `name`
  - `display_name`
  - `description`
- instructions
  - `body`
- setup
  - `requirements`
- provider extensions
  - `provider_config`
- artifacts
  - `files`
- lifecycle
  - revision history
  - approval history
  - publish/archive state

The package content is the source of truth. The following fields are derived on
read or lifecycle transitions:

- `validation_problems`
- `publish_ready`
- `runtime_available`
- `has_unpublished_changes`

These values may be cached, but they are not a second persisted truth source.

## Skill Package Spec

The current on-disk skill package format is:

- required:
  - `skill.md`
- optional:
  - `requires.yaml`
  - `claude.yaml`
  - `codex.yaml`
  - additional files and scripts that the skill references at runtime

### `skill.md`

Primary instruction body plus optional frontmatter metadata such as:

- `name`
- `display_name`
- `description`

### `requires.yaml`

Credential requirements used during setup. Each requirement can define:

- `key`
- `prompt`
- `help_url`
- optional validation rules

### Provider config files

Provider-specific configuration can live in:

- `claude.yaml`
- `codex.yaml`

These files extend the runtime context for the relevant provider without
changing the shared skill lifecycle.

### Additional files

Additional files are stored as text artifacts inside the package. They are used
for helper scripts, templates, or supporting content referenced by the skill at
runtime.

Shared package policy:

- safe relative paths only
- reserved package filenames may not be reused
- shell scripts are the only files that may be marked executable
- attached file limits are:
  - at most 16 files
  - 64 KB per file
  - 256 KB total
- file count and file size limits are validated in the backend
- registry uploads and chat-provided file mutations go through the same
  ingestion and validation rules

## Validation And Lifecycle Rules

- validation is backend-owned, not client-owned
- submit and publish both invoke shared validation
- clients show the same validation problems, even if they present them
  differently
- invalid drafts can be saved only if they still satisfy package policy;
  submit/publish remain blocked until validation passes

Registry and chat are peers here:

- registry can show inline panels, lists, and guided flows
- chat can expose the same backend operations in smaller or more text-oriented
  steps
- neither client is allowed to invent a separate lifecycle or draft format

Current client exposure over the same backend operations:

- registry `Skills -> Studio`
  - package-aware draft editing
  - validation/readiness display
  - lifecycle actions
- Telegram `/skills package <name>`
  - inspect the full draft package JSON
- Telegram `/skills package <name> <json>`
  - replace the full draft package

The registry is the richer wrapper, not the authority. Chat remains a peer
client.

## Product Rules

- Store listings feed the same `Catalog -> Available on this bot` flow. The store is
  a source, not a separate product concept.
- Custom skills use the same install and activation model after they are
  published.
- Core, Store, and Custom skills share one logical package model even if their
  ingestion paths differ (disk seed, store import, in-product draft authoring).
- User-facing copy should prefer:
  - `Catalog`
  - `Available on this bot`
  - `Default for new conversations`
  - `Active in this conversation`
  - `Routing skills`
  - `Needs setup`
  - `Ready`
  - `Core / Store / Custom`

Avoid surfacing internal-only terms such as `builtin` or a competing end-user
`capabilities` concept as the primary UX label.
