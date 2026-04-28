# Skills Model

This is the technical model behind the registry `Capabilities` surface.

The current runtime noun is `skill`. The current UI/product noun is
`capability`. They refer to the same product concept.

## Core State Layers

Every client must preserve these distinct states:

1. `Catalog`
   What skills/capabilities exist.
2. `Available on this bot`
   Which skills one agent can use.
3. `Default for new conversations`
   Which available skills seed future conversations.
4. `Active in this conversation`
   Which skills are active in one conversation.
5. `Routing skills`
   Which skills this agent advertises for delegation/routing.

Rules:

- availability does not imply active everywhere
- default does not update old conversations
- conversation activation does not change bot-level availability
- routing is derived, not separately authored

## Orthogonal Dimensions

| Dimension | Values |
| --- | --- |
| Source | Core, Store, Custom, Generated |
| Kind | prompt, executable |
| Setup | Needs setup, Ready |
| Lifecycle | Draft, Submitted, Approved, Published, Archived |

Generated/rehearsal/test skills must be identifiable so default human surfaces
can hide them.

## Routing Skills

Routing skills are derived from:

- bot-level availability
- runtime readiness
- registry routing policy

Routing may also apply policy dimensions such as region, trust, tier, or
compliance. Those dimensions do not replace skills and should not be presented
as another skill catalog.

## Shared Operations

Backend-owned operations include:

- list/search catalog
- inspect skill
- install/update/uninstall store skill on a bot
- activate/deactivate/clear conversation skills
- start setup and submit credential values
- create/edit/submit/approve/reject/publish/archive custom skills
- export/import custom skill packages

Registry UI and Telegram may present these differently, but must call the same
backend operations.

## Draft Package Model

Custom skills use a package shape compatible with Core and Store skills.

Mutable draft content:

- name
- display name
- description
- instruction body
- requirements
- provider config
- files
- revision/lifecycle metadata

Derived fields:

- validation problems
- publish readiness
- runtime availability
- unpublished changes

Derived fields may be cached, but they are not a second source of truth.

## On-Disk Package Shape

Required:

- `skill.md`

Optional:

- `requires.yaml`
- `claude.yaml`
- `codex.yaml`
- additional files/scripts

Policy:

- safe relative paths only
- reserved package filenames may not be reused
- only `.sh` files may be executable
- at most 16 files
- 64 KB per file
- 256 KB total

## Validation And Lifecycle

Validation is backend-owned.

Rules:

- clients do not invent validation rules
- submit and publish invoke shared validation
- invalid drafts can be saved only if they satisfy package safety policy
- publish remains blocked until validation passes
- lifecycle actions require permissions

## Client Exposure

Registry UI:

- richer editing and review flow
- search/filter catalog
- bot availability
- conversation activation
- custom draft lifecycle
- package import/export

Telegram:

- text-oriented commands over the same backend
- add/remove/list active skills
- import/export where permitted
- lifecycle actions only where permissions allow

## Product Copy

Prefer user-facing copy:

- Capability
- Catalog
- Available on this bot
- Default for new conversations
- Active in this conversation
- Routing skills
- Needs setup
- Ready
- Core / Store / Custom / Generated

Avoid exposing internal-only terms such as `builtin` or creating a competing
end-user noun for the same concept.
