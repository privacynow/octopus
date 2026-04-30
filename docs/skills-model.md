# Skills Model

`Skill` is the product noun and runtime noun. A skill is a reusable
instruction/tool package that can be installed, activated, routed to, and
executed through shared SDK workflows.

## State Layers

Every client must preserve these distinct states:

1. `Catalog`: skills known to Octopus.
2. `Available on this bot`: skills one agent runtime can use.
3. `Default for new conversations`: available skills seeded into future
   conversations.
4. `Active in this conversation`: skills active in one conversation.
5. `Routing skills`: derived routing projection for delegated work.

Rules:

- availability does not imply active everywhere
- defaults do not update old conversations
- conversation activation does not change bot-level availability
- routing is derived, not separately authored

## SDK Interfaces And Implementations

The SDK owns the interfaces. Concrete runtimes implement them:

| Interface area | Examples |
| --- | --- |
| Transport interfaces | Telegram transport, registry delivery transport. |
| Registry participant interface | Enrollment, conversations, routed work, events, health. |
| Management protocol | Skill catalog, skill lifecycle, conversation skills, guidance, execution reset. |
| Stores/providers | Postgres stores, Claude/Codex providers, credential stores. |

Registry UI and Octopus CLI are admin clients. Telegram is a transport client.
All should use the same SDK workflows and management operations rather than
inventing client-specific behavior.

## Admin Operations

Management support is expressed as concrete supported admin operations, not as
generic buckets.

Examples:

- `list_catalog_skills`
- `search_catalog_skills`
- `catalog_skill_detail`
- `catalog_skill_lifecycle_detail`
- `edit_catalog_skill_draft`
- `publish_catalog_skill`
- `conversation_skill_state`
- `activate_conversation_skill`
- `clear_conversation_skills`

## Package Shape

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

## Product Copy

Prefer:

- Skill
- Catalog
- Available on this bot
- Default for new conversations
- Active in this conversation
- Routing skills
- Needs setup
- Ready
- Core / Store / Custom / Generated

Avoid:

- legacy synonyms for skill
- vague statements about what an agent "supports"
- client-specific lifecycle names that bypass SDK workflow terms
