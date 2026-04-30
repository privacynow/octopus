# Protocol Assignment Audit

This document records the current assignment contract and the intended product
direction for protocol authoring.

## Product Rule

Assignment belongs to the stage.

Participants/roles are reusable identity and shared instruction records. They
are not the primary assignment authority for a stage.

## Current Runtime Rule

- Canonical authored stage assignment is `stage.selector`.
- A stage also references `participant_key` for role/instruction context.
- Legacy `participants[].selector` and `required_skills` are canonicalization
  inputs only.
- Runtime selector dispatch reads the selected stage selector.
- Skill selectors may prefer the run entry agent when no explicit
  `preferred_agent_id` is pinned and the entry agent satisfies the selector.
- `preferred_agent_id` is a runtime hint, not a second authored assignment
  field.

## Current Draft Vs Publish Behavior

The UI may allow incomplete or unassigned stages while an author is drafting.

Current publish validation still blocks stages that do not resolve an
assignment/selector. That is current implementation behavior, not a reason to
show internal selector plumbing to standard authors.

If product direction changes to allow published unassigned/manual stages, this
document, `octopus_sdk/protocols/documents.py`, protocol UI validation, runtime
dispatch, and tests must change together.

## Standard Authoring Surface

Standard authors should see:

- stage title
- stage instructions
- clear assignment summary
- skill choice where desired
- agent choice where desired
- matching-agent quick choices when the list is small
- scalable selector when the list is larger
- artifacts
- routing/transitions

Standard authors should not see:

- raw `stage_key`
- custom runtime selector internals
- `max_rounds`
- `timeout_seconds`
- operator-only runtime fields

Delete/remove actions should be visible in the stage flow, not hidden inside an
internal `Advanced` section.

## Surface Audit

| Surface | Assignment responsibility | Expected behavior |
| --- | --- | --- |
| Protocol stage stack | Shows one compact assignment summary. | No duplicate assignment prose. |
| Stage editor | Owns assignment editing. | Author can choose none while drafting, agent, skill, or skill with preferred agent. |
| Role/participant editor | Owns reusable role identity and shared instructions. | Does not become the primary assignment editor. |
| Workflow map | Shows structure and optional context. | Not required for primary authoring. |
| Registry runtime/store | Resolves stage selector and run participant state. | Runtime reads stage-owned assignment. |

## Validation Issue Contract

Current validation lives in:

- `octopus_sdk/protocols/documents.py`

Current assignment-related issues include:

- `stage.selector_required`
- `stage.selector_kind_required`
- `stage.selector_kind_invalid`
- `stage.selector_value_required`
- `participant.legacy_multi_skill`

UI entry point:

- `_validationEl()` in `octopus_registry/ui/js/components/protocol-workspace.js`

Expected behavior:

- draft editing can be incomplete
- publish validation reports assignment issues clearly
- missing assignment must not silently fall back to an arbitrary agent
- user-facing summaries derive from the same stage selector contract
