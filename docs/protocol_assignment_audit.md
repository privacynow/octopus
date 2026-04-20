# Protocol Assignment Audit

This artifact locks the active assignment and validation contract for protocol authoring.

## Runtime rule

- Canonical authored assignment: `stage.selector`
- Participants are reusable role records only: `participant_key`, display metadata, shared instructions
- Legacy `participants[].selector` and `required_skills` are migration inputs only during document canonicalization
- Runtime selector dispatch reads only the selected stage's `selector`
- Skill selector runtime preference still applies: when a protocol run starts from an entry agent and a step uses a skill selector without an explicit `preferred_agent_id`, runtime resolution prefers the run entry agent if that agent satisfies the selector
- `preferred_agent_id` remains a runtime hint, not a second authored assignment field

## Surface audit

| Surface | Assignment formatter / summary | Validation entry point | Expected user-visible state |
| --- | --- | --- | --- |
| Workflow canvas | `_stageNodeSublabel()` / `_stageAssignmentSummary()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Steps show owner role plus one compact assignment summary derived from the stage selector |
| Workflow outline | `_sceneOutline()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Outline stays structural: section and step labels only, no duplicate selector prose |
| Step editor hero and assignment section | `_stageEditorHero()` / `_selectorEditor()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` plus inline preview in `_selectorEditor()` | Authors can fully configure assignment in the step editor without leaving the step flow |
| Role editor | `_participantEditorShell()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) | Lifecycle validation surface from `_validationEl()` | Role editor only manages reusable role identity and shared instructions; it is not an assignment authority |
| Registry runtime/store | `dispatch_target_selector()` in [`engine.py`](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/engine.py) and store projection in [`protocol_store.py`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/protocol_store.py) | runtime blocked decision / store snapshot fields | Runtime and snapshots read stage selectors; participant rows are runtime role state, not canonical authored assignment |

## Validation issue contract

Validation is authoritative in [`documents.py`](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py):

- `stage.selector_required`
- `stage.selector_kind_required`
- `stage.selector_kind_invalid`
- `stage.selector_value_required`
- `participant.legacy_multi_skill`

UI entry point:

- `_validationEl()` in [`protocol-workspace.js`](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)

Expected behavior:

- missing stage selector blocks publish
- missing stage selector never silently falls back to entry agent
- skill selectors may still prefer the run entry agent at runtime when that agent matches the authored skill
- every user-facing assignment summary is derived from the same stage selector contract
