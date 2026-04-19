# Protocol Assignment Audit

This artifact locks the active assignment and validation contract for protocol authoring.

## Runtime rule

- Canonical authored assignment: `participant.selector`
- Legacy `required_skills`: migration input only
- Runtime selector dispatch: explicit selector only
- Skill selector runtime preference: when a protocol run starts from an entry agent and a participant uses a skill selector without an explicit `preferred_agent_id`, runtime resolution prefers the run entry agent if that agent satisfies the skill selector
- `preferred_agent_id` remains a runtime hint, not a second authored assignment field

## Surface audit

| Surface | Assignment formatter / summary | Validation entry point | Expected user-visible state |
| --- | --- | --- | --- |
| Workflow overview | `_participantRuntimeLabel()` via segment participant summary in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Section ownership reads as participant plus assignment rule; invalid drafts still show validation issues in the details column |
| Detail header and participant chips | `_participantRuntimeLabel()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Selected section and participant chips show the same participant plus assignment summary as Overview |
| Step card owner line | `_participantAssignmentSummary()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Each step shows owning participant and current runtime assignment summary |
| Step editor hero and runtime assignment panel | `_participantAssignmentSummary()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` plus explicit empty-state copy in `_stageAssignmentPanel()` | Missing owner or selector reads as incomplete, not as hidden fallback behavior |
| Participant editor | `_selectorSummary()` / `_participantAssignmentSummary()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Participant editor shows one authored assignment rule and surfaces `selector_required` through validation |
| Topology node labels | `_participantRuntimeLabel()` / `_stageNodeSublabel()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Focused topology nodes show participant plus assignment summary without introducing a second routing model |

## Validation issue contract

Validation is authoritative in [`documents.py`](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py):

- `participant.selector_required`
- `participant.selector_kind`
- `participant.selector_value`
- `participant.legacy_multi_skill`

UI entry point:

- `_validationEl()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)

Expected behavior:

- missing selector blocks publish
- missing selector never silently falls back to entry agent
- skill selectors may still prefer the run entry agent at runtime when that agent matches the authored skill
- every user-facing surface uses the same selector-derived summary helpers above
