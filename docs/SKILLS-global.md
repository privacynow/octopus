# Global Skills Reference

Applies to all projects. Repo-specific skill locations and patterns are in the
repo-root `SKILLS.md`.

## What Skills Are

Skills are structured, reusable prompt templates that activate a specific mode of
analysis or hardening before a developer or AI agent changes code. They are
meta-tooling: they make AI assistance more systematic and prevent known failure
classes from recurring.

A skill file contains:

1. **Trigger condition** — exactly when this skill must be opened before coding
2. **Pre-coding checklist** — questions that must all be answered before any change
3. **During-coding guards** — things that must remain true throughout the change
4. **Acceptance criteria** — what must be true before the change is considered done

## The Skill Contract

**If the current task matches a skill's trigger condition, open the skill file and
follow it completely before touching code.** Do not rely on memory. Read the skill
fresh. Doing this once prevents an entire class of bugs from reaching production.

Skills are not optional checklists. They encode lessons from real production
incidents. Skipping a skill on a "small" change is how the most expensive bugs are
introduced — because production incidents often start with a change that seemed too
small to warrant rigor.

## Skill Categories

### Contract Change Skills

Used when changing public interfaces, port contracts, or the shape of data that
crosses a module boundary. These prevent callers from breaking silently.

Checklist core:
- What is the exact old contract and the exact new contract?
- Which call sites depend on the old shape? Enumerate with `rg`, do not guess.
- Which tests assert the old contract? Update them — do not delete them.
- Is there a migration path for durable state that was serialized under the old shape?

### Durable State Hardening Skills

Used when changing state-machine transitions, work-item lifecycle, session
persistence, or recovery logic. These prevent state corruption and silent data loss.

Checklist core:
- What states exist? What are all legal transitions?
- Who marks success, who marks failure, who marks claimed?
- What happens if the process is killed mid-transition?
- What does recovery produce if the same item is replayed twice?
- Is there a path that leaves state poisoned with no recovery?

### Invariant Test Builder Skills

Used when writing tests for orchestration, state machines, or any code where the
important correctness property is "this cannot happen" rather than "this scenario
produces this output."

Checklist core:
- What is the invariant (the thing that must always / never be true)?
- What is the oracle — the exact object or persisted state the test observes?
- Is the oracle the same object the user sees / that production depends on?
- Is there a false-positive test (a near-miss that must not trigger the same outcome)?

### Progress UX Skills

Used when changing user-visible progress, status messages, or output rendering.
These prevent leaking internals, confusing users with false state, and missing
edge formatting.

Checklist core:
- What does the user see on success, on failure, on cancellation, on timeout?
- Does any message include a provider name, thread ID, or internal identifier?
- Does the message remain accurate if the underlying operation is interrupted?
- Is there a test that proves the user-visible text (not the internal state) is correct?

## Pluggable Subsystem Skills (Port + Factory)

The single most important architectural skill for any project with pluggable
subsystems is the Port + Factory Rule (documented in `docs/AGENTS-global.md`).
Before adding or modifying any subsystem that could have multiple implementations:

1. Confirm the port (abstract interface) exists.
2. Confirm the factory exists and is the only place that constructs implementations.
3. Confirm orchestration code imports only the port.
4. Confirm the new implementation is added only to the adapter file and the factory.

If any of these four are not true, fix the structure before adding the new feature.

## Writing New Skills

A new skill is warranted when:
- A failure class has recurred at least twice despite being in a bug-class list.
- The pre-coding analysis for a type of change is complex enough that it cannot be
  reliably done from memory.
- A new architectural pattern (e.g. port+factory, durable-state machine) has been
  established and needs to be consistently applied to future changes of that type.

Structure:
```markdown
# Skill: <Name>

## Trigger
Open this skill before: <exact condition>

## Pre-Coding Checklist
- [ ] <question that must be answered>
- [ ] ...

## During-Coding Guards
- <thing that must remain true>

## Acceptance Criteria
- <what must be provably true when done>
```
