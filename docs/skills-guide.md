# Skills Guide

Skills are reusable instruction/tool packages that agents can use in
conversations, protocol stages, and routed work. Do not introduce a second
product noun for the same concept.

## Vocabulary

| Product term | Meaning |
| --- | --- |
| Catalog | Skills known to Octopus. |
| Available on this bot | Skills installed and ready for a specific agent runtime. |
| Default for new conversations | Available skills that seed future conversations. |
| Active in this conversation | Skills currently applied to one conversation. |
| Routing skills | Derived projection used for delegation and assignment. |

Routing skills are not a second skill system. They are derived from normal
skill availability, runtime readiness, and registry routing policy.

## Sources

Skills can come from:

- `Core`: built into the runtime image.
- `Store`: installed from the skill store.
- `Custom`: authored inside Octopus.
- `Generated`: created by protocol, rehearsal, or test flows.

Generated entries should not dominate default human lists. Use explicit filters
when you need generated or rehearsal entries.

## Common Workflows

### Browse Skills

Open:

```text
Build -> Skills
```

Use search and filters rather than scanning long skill walls.

### Make A Skill Available On A Bot

1. Open `Skills`.
2. Choose the agent/bot context.
3. Find the skill.
4. Install or enable it.

This does not activate the skill in every existing conversation.

### Activate A Skill In One Conversation

1. Open the conversation.
2. Open `Skills`.
3. Activate the skill.
4. Complete setup if required.

This affects only that conversation.

### Author A Custom Skill

1. Open `Skills`.
2. Choose a bot that implements the skill lifecycle admin operations.
3. Create a draft.
4. Write title, description, and instructions.
5. Define setup requirements if needed.
6. Validate, submit, review, and publish where permitted.
7. Export or import package content when needed.

The registry UI and Telegram should call the same SDK workflow and management
operations. If a skill operation exists only in one client, that is an
architecture gap.

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

## Routing

Routing is operational. A routing skill is:

- available on the bot
- runtime-ready
- allowed by routing policy

Routing diagnostics belong under `Operations -> Routing`, not as a second skill
catalog.

For the lower-level model, use [skills-model.md](skills-model.md).
