# Protocol Author Guide

This guide describes the current protocol authoring model in the registry UI.

Protocols are reusable staged workflows. Templates are user-authored protocols
published as reusable snapshots; they are managed inside the Protocols surface.

## Current Authoring Surface

Open:

```text
Build -> Protocols
```

You can currently:

- create a protocol from blank
- copy a saved user-authored template when one exists
- edit stages inline
- add a stage below the current stage
- remove stages
- configure assignment
- declare artifacts
- define transitions/routing
- show the workflow map on demand
- validate and publish
- publish a protocol as a user-authored template

The UI is being consolidated around one progressive stage editor. If a change
introduces a separate drawer, duplicate editor, or disconnected assignment
surface, that is not the intended product direction.

## Definition Model

A protocol definition contains:

- metadata: slug/display name/description
- participants: reusable role identity and shared instructions
- stages: ordered steps
- stage assignment: the runtime target selector for that stage
- artifacts: named inputs/outputs
- transitions: routing decisions between stages
- policies: review limits and lifecycle behavior

Drafts can change. Published versions are immutable execution contracts.
JSON and YAML are two text views over the same canonical protocol document.

## Stages

Stage kinds:

- `work`
- `review`
- `acceptance`

Standard authoring should expose:

- title
- instructions
- assignment
- artifacts
- routing/transitions
- rehearsal or validation feedback

Standard authoring should not expose:

- raw `stage_key` editing
- custom runtime selector internals
- `max_rounds`
- `timeout_seconds`
- low-level operator controls

Those fields may still exist in the protocol document/runtime model. They are
operator/internal controls and must remain gated.

## Assignment

Assignment is stage-owned.

Current stage assignment forms:

- no assignment while drafting
- agent-oriented assignment
- skill-oriented assignment
- skill with a preferred matching agent
- role/participant-based assignment where the role carries shared instructions

Current publish validation still expects stages to resolve an assignment before
publication. Draft editing may permit incomplete stages so authors can build
progressively.

Important distinction:

- participant/role records define reusable identity and shared instructions
- stage assignment decides who or what executes a specific stage

Do not treat the role editor as the primary assignment editor.

## Artifacts

Artifacts are the contract between stages and the visible output of runs.

For workspace file artifacts:

- paths must be relative to the workspace root
- absolute paths are rejected
- parent traversal such as `../` is rejected
- declared outputs may be visible before they are produced
- produced outputs should offer preview/open/download/copy actions wherever
  artifact actions are implemented

If an artifact appears in a protocol/run/stage but cannot be opened or
downloaded after production, that is a product gap to fix.

## Transitions And Review Loops

Review and acceptance stages require explicit decisions from their transition
map.

Common decisions:

- approve
- revise
- reject
- accept

Review loops are bounded by policy. Exceeding review limits blocks the run
rather than looping forever.

## Draft Workflow

Recommended workflow:

1. open `Protocols`
2. create from blank, or copy a saved user-authored template when one exists
3. name the protocol
4. add/edit stages in order
5. configure each stage assignment
6. declare inputs/outputs
7. connect routing/transitions
8. show the workflow map only when spatial context helps
9. validate
10. publish
11. optionally publish as template

## JSON/YAML Contract

JSON/YAML import/export are text views over the shared protocol document model
in `octopus_sdk/protocols/`.

Do not add a browser-only protocol format or a script-only format. Registry UI,
registry API, SDK helpers, and Telegram-facing protocol commands must converge
on the shared model.

## Templates

Templates are not built into the default product path. A template exists only
after a user publishes a protocol and chooses `Publish as template`. Copying a
template creates a separate editable protocol; it does not mutate the saved
template.

Use templates for workflows your team has already authored and wants to reuse.
Use `New protocol` for new workflow design.
