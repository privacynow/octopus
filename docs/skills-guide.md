# Capabilities And Skills Guide

The registry UI labels the build surface as `Capabilities`. The underlying
runtime model still uses `skills`.

Use this guide when managing what agents can do.

## Vocabulary

| UI/Product term | Runtime term | Meaning |
| --- | --- | --- |
| Capability | Skill | A reusable ability/instruction/tool package. |
| Available on this bot | Bot skill availability | The agent can use this skill. |
| Default for new conversations | Conversation seed list | New conversations start with this skill active. |
| Active in this conversation | Session skill activation | This one conversation currently uses the skill. |
| Routing skills | Routing projection | Skills this agent advertises for delegated work. |

Do not treat routing skills as a second skill system. They are derived from
normal skill availability, runtime readiness, and registry routing policy.

## Sources

Skills/capabilities can come from:

- `Core`: built into the runtime image
- `Store`: installed from the skill store
- `Custom`: authored inside Octopus
- `Generated`: created by protocol/rehearsal/test flows

Generated entries should not dominate default human lists. Use filters when you
need them.

## Kinds

Current execution kinds:

- `prompt`: adds selected instructions to the provider context
- `executable`: participates in runtime orchestration, not only prompt text

Both kinds share the same availability/default/active model.

## Common Workflows

### Browse Capabilities

Open:

```text
Build -> Capabilities
```

Use search and filters rather than scanning long skill walls.

### Make A Skill Available On A Bot

1. open `Capabilities`
2. choose the agent/bot context
3. find the skill
4. install or enable it

This does not activate it in every existing conversation.

### Activate A Skill In One Conversation

1. open the conversation
2. open its skill/capability controls
3. activate the skill
4. complete setup if required

This affects only that conversation.

### Make A Skill Default

Use bot-level controls to make a skill a default for new conversations.

This affects future conversations only.

### Author A Custom Skill

Custom skills are authored from the unified Capabilities/Skills backend.

Typical registry flow:

1. create a draft
2. write title, description, and instructions
3. define setup requirements
4. validate
5. submit/review/publish where permitted
6. export/import package content when needed

The UI may group low-level package details under an advanced/detail section,
but normal users should not be forced through internal package fields for basic
skill creation.

## Package Model

A skill package can include:

- `skill.md`
- `requires.yaml`
- `claude.yaml`
- `codex.yaml`
- supporting files/scripts

Policy:

- safe relative paths only
- reserved package filenames may not be reused
- only `.sh` files may be executable
- file count and size limits are backend-enforced
- registry and chat mutations use the same validation rules

## Telegram

Telegram exposes text-oriented operations over the same backend model.

Examples:

```text
/skills
/skills list
/skills add <name>
/skills remove <name>
/skills export <name>
/skills import
```

Admin lifecycle actions require permissions.

## Routing

Routing is operational.

A routing skill is:

- available on the bot
- runtime-ready
- allowed by routing policy

Routing diagnostics belong under Operations -> Routing, not as a second skill
catalog.

## Current Product Gaps To Watch

- The UI should not show intimidating unfiltered walls of generated skills.
- Agent pages should summarize capabilities instead of duplicating the full
  catalog.
- Any operation available in Telegram should use the same backend lifecycle as
  the registry UI.
- If a skill/capability is needed while authoring a protocol stage and does not
  exist, the product direction is to allow creating it through the UI instead
  of blocking the author.

For the lower-level model, use [skills-model.md](skills-model.md).
