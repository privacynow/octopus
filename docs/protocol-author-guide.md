# Protocol Author Guide

This guide is for authors and publishers defining protocol workflows in the
registry.

## Definition Model

A protocol definition contains:

- metadata: `slug`, `display_name`, `description`
- participants: reusable worker/reviewer identities with optional selectors and
  required skills
- artifacts: named workflow outputs or inputs
- stages: ordered work, review, or acceptance steps
- policies: shared lifecycle rules such as single active writer and max review
  rounds

Definitions are versioned. Drafts can change; published versions are immutable.

## Stage Kinds

V1 stage kinds are:

- `work`
- `review`
- `acceptance`

`work` stages default to `completed` if their transitions omit decisions.
`review` and `acceptance` stages require explicit decisions from their declared
transition map.

## Participants And Resolution

Each stage references one `participant_key`.

Resolution order is:

1. explicit `participant.selector`, if present
2. otherwise the first `required_skills` entry as a skill selector with the
   run entry agent as preferred target
3. otherwise the run entry agent directly

Ambiguity is an error. Multiple matches without a preferred agent do not fall
through to “pick one.” Fix the selector or the registry data instead.

## Artifacts

Artifacts are the durable contract between stages.

For `workspace_file` artifacts:

- `path` must be relative to the workspace root
- absolute paths are rejected
- parent traversal such as `../` is rejected
- verification is required in this release

The current release is in waiver mode A:

- `artifact.verify: false` is rejected at validation/publish time

Runtime artifact observations supply:

- path
- existence
- size
- content hash
- modified time
- verification state

The registry keeps the latest non-superseded observation per `artifact_key` as
the current manifest view.

## Strict Completion

Use these stage controls intentionally:

- `strict_completion: true`
  requires explicit protocol completion lines for work stages
- `require_output_verification: true`
  requires artifact observation success before advancement
- `timeout_seconds`
  sets wall-clock stage timeout handled by registry maintenance

## Review Loops And Policies

`policies.max_review_rounds` caps revise loops. Exceeding the cap blocks the
run with `max_review_rounds_exceeded`; it does not loop forever.

`policies.single_active_writer` enforces one write-capable running stage at a
time through the shared lease path.

## Draft Workflow

Recommended authoring flow:

1. create or import a draft in `Protocols`
2. edit as JSON or YAML
3. validate
4. diff against the last published version
5. publish
6. archive when retiring the definition

The registry UI and API share the same document parser, validator, export, and
diff logic. Do not author a separate browser-only or script-only format.

## JSON/YAML Contract

JSON and YAML are two text views over the same canonical protocol document
model. The registry UI, API, SDK client, and checked-in OpenAPI contract all
use the same shared conversion helpers from `octopus_sdk/protocols.py`.

## Software Engineering Template

The built-in `software-engineering` protocol is the seeded baseline template.
Use it when you want:

- planning and review
- architecture and review
- implementation and review
- acceptance

Clone it into a draft, then specialize participants, artifacts, instructions,
and review policies rather than inventing a parallel lifecycle.
