# telegram-agent-bot: Skills Reference

This supplements [docs/SKILLS-global.md](/home/tinker/telegram-agent-bot/docs/SKILLS-global.md)
with repo-specific skill patterns, codex skill locations, and how the bot's
credential-based skill system works.

## What "Skills" Means Here

The word "skills" has two distinct meanings in this repo. Both matter.

### 1. Codex AI-Agent Skills (docs/codex-skills/)

Structured prompt templates that activate a specific mode of review or hardening
before a developer or AI agent changes code. These are meta-skills: they make AI
assistance safer and more systematic.

Available skills:

| Skill | When to use |
|---|---|
| `docs/codex-skills/contract-change-audit/SKILL.md` | Before changing any public interface, port contract, or durable-state schema |
| `docs/codex-skills/durable-state-hardening/SKILL.md` | Before changing work-item state transitions, session persistence, or recovery logic |
| `docs/codex-skills/invariant-test-builder/SKILL.md` | Before writing tests for orchestration, completion ownership, or state-machine logic |
| `docs/codex-skills/progress-ux-audit/SKILL.md` | Before changing user-visible progress, status messages, or output rendering |

**Rule:** For any nontrivial change that falls into one of these categories, open
the matching skill file before touching code. Do not rely on memory of what the
skill says — read it fresh each time.

### 2. Bot Runtime Skills (session.active_skills / SkillDefinition)

Credential-bound capabilities that the bot loads at startup and activates per
conversation. These are first-class product features, not developer tooling.

#### Shape

```python
# app/config.py
@dataclass
class SkillDefinition:
    name: str
    description: str
    enabled: bool = True
    # ... provider-specific fields

# app/session_state.py
@dataclass
class SessionState:
    active_skills: list[str]      # resolved skill names for this session
    # ...
```

#### Resolution Rule

Use the **resolved** active skills list (`session.active_skills`), never
`cfg.skills` or the raw config list, in any safety-sensitive or user-visible
context. Raw config is persistence-only. Resolved state is authority.

This is Bug Class 2 in AGENTS.md — violations in this area have caused repeated
production bugs.

#### Skill Activation Path

```
BotConfig.skills (config)
    → skill_resolver.resolve(user, session) → [resolved list]
        → SessionState.active_skills (runtime authority)
            → execute_request() / provider dispatch
```

Any new skill feature must go through the resolver. Do not read `cfg.skills`
directly in orchestration code.

#### Trust and Access Control

Skills may be gated by trust tier. The trust tier is determined by the factory
(`app/transports/factory.py:trust_tier_for_source()`), not by inline `source`
string checks. A skill that checks trust must use the resolved tier from the
surface factory output, never `if source == "telegram":` inline.

## Adding a New Skill

1. Add `SkillDefinition` entry to `app/config.py` with `name`, `description`, and
   any credential fields.
2. Add resolution logic in the skill resolver if access is gated.
3. Add the skill name to the relevant provider prompt builder.
4. Add a test: `test_skill_<name>_resolved_and_active` — proves the skill appears
   in `session.active_skills` under the correct conditions.
5. Add a test: `test_skill_<name>_not_resolved_without_credential` — proves it
   does not appear when the gate condition is not met.

## Adding a New Codex AI-Agent Skill

1. Create `docs/codex-skills/<skill-name>/SKILL.md`.
2. The skill file must include: trigger condition, checklist of questions to answer
   before coding, and minimum acceptance criteria.
3. Add a reference in both `AGENTS.md` (repo-specific) and this file.
4. Test the skill by running it against a real recent change to verify the checklist
   catches what it claims to catch.
