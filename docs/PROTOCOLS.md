# Protocol Guide

Protocols are reusable staged workflows. Use them when the work needs a known
sequence, assigned execution, review decisions, declared outputs, and a record
of what happened.

Use conversations for ad hoc work. Use protocols when you want a workflow that
another person can run, inspect, export, import, and improve.

## When To Use A Protocol

Use a protocol for:

- repeatable customer or operational workflows
- work that produces named artifacts
- multi-agent or skill-routed execution
- review or acceptance loops
- workflows that need an audit trail
- work you may export and share with another Octopus environment

Do not use a protocol just to send one normal chat message.

## Anatomy

| Part | Meaning |
| --- | --- |
| Metadata | Slug, display name, description, and optional custom run inputs. |
| Participant | Reusable role identity and shared instructions. |
| Stage | One ordered step in the workflow. |
| Assignment | The agent, role, or skill target for a stage. |
| Transition | The next stage after a decision or completion state. |
| Artifact | A named input or output, usually a workspace file. |
| Policy | Review limits and lifecycle behavior. |
| Run | One execution of a published version. |

Drafts can change. Published versions are immutable execution contracts.

## Authoring Workflow

Open:

```text
Build -> Protocols
```

Recommended flow:

1. Click `New protocol`.
2. Choose `Start blank`, or copy a user-authored template.
3. Name the protocol with a clear human title and stable slug.
4. Add stages in execution order.
5. Write stage instructions as the real work contract.
6. Configure each stage assignment.
7. Declare artifacts and attach stage inputs/outputs.
8. Configure transitions and review loops.
9. Validate.
10. Publish.
11. Start a run from the published version.

Standard authoring should expose title, instructions, assignment, artifacts,
routing, validation, and run feedback. It should not expose raw runtime
selectors, raw stage keys, timeout fields, max-round internals, or custom
operator controls to normal authors.

## Stages

Common stage kinds:

- `work`: an agent performs work
- `review`: a reviewer decides whether work should continue or be revised
- `acceptance`: final acceptance or rejection

Write stage instructions as if the assignee will only see that stage, its
declared inputs, run context, and the workflow contract. Avoid relying on a
human to restate artifact filenames or private implementation details at launch
time.

## Assignment

Assignment belongs to the stage.

Supported authoring choices include:

- no assignment while drafting
- a specific agent
- a skill
- a skill with a preferred matching agent
- a role/participant assignment

Participants define reusable identity and shared instructions. Stage assignment
decides who or what executes a specific stage. Do not use the participant
editor as the primary assignment editor.

Publish validation expects every executable stage to resolve an assignment.
Draft editing may allow incomplete stages so authors can build progressively.

## Artifacts

Artifacts are the output contract.

For workspace file artifacts:

- use paths relative to the workspace root
- do not use absolute paths
- do not use parent traversal such as `../`
- declare output artifacts before the run
- treat produced artifact actions as part of the user experience

The run page should show declared and produced artifacts clearly. Produced
artifacts should offer preview, open, download, copy path, or package browsing
where the host can resolve them.

## Starting A Run

Runs start from the latest published protocol version, not unsaved draft edits.

From the Registry UI:

1. Open `Build -> Protocols`.
2. Choose a published protocol.
3. Click `Run protocol`.
4. Select an execution-healthy entry agent.
5. Fill the launch fields.
6. Review the declared artifact contract.
7. Start the run.
8. Inspect it from `Work -> Runs`.

Unless the protocol defines custom `metadata.run_inputs`, launch uses the
shared generic fields:

- workspace
- goal or problem statement
- additional context
- constraints

Launch context is included in stage prompts so agents understand this specific
run. It does not rewrite stages, assignments, skills, transitions, or artifact
paths. If a workflow needs specialized launch fields, define them in
`metadata.run_inputs` so every launch surface reads the same contract.

## Reading A Run

Open:

```text
Work -> Runs
```

Read the run through:

- `Overview`: status, protocol version, entry agent, current stage, actions
- `Stages`: stage status, assignment, inputs, outputs, linked work
- `Artifacts`: declared and produced outputs
- `Audit`: launch context, transitions, decisions, and operator actions

The user should be able to answer:

- what ran?
- which version ran?
- who or what executed each stage?
- what files were expected?
- what files were produced?
- what is blocked, waiting, failed, canceled, or complete?

## Operator Actions

Supported run actions include:

- `retry`
- `accept`
- `send-back`
- `cancel`

Actions are permission-gated, version checked, and recorded in run history.
Corrective or destructive actions should require a reason where applicable.

## Export And Import

Protocol packages are single text documents in JSON or YAML. They are not zip
files.

An exported protocol package includes:

- the protocol document
- required skill package documents embedded in the same file
- source binding metadata that helps the receiving environment map stages to
  local bots
- package metadata and hash information

JSON and YAML are two text views over the same canonical protocol document.
Choose the format that is easiest for the receiving person or system to review.

Export from `Build -> Protocols` with `Export package`. Prefer exporting the
published version when sharing with a customer or another environment.

Import from `Build -> Protocols` with `Import package`:

1. paste or upload the package JSON/YAML
2. choose `Review import`
3. resolve any stage-to-bot mapping that cannot be inferred
4. choose the protocol policy
5. import

When the protocol slug already exists, import defaults to `Import as copy`.
Supported policies are:

- `Create new`: create the protocol when no matching slug exists
- `Import as copy`: create a duplicate with a suggested copy name and slug
- `Overwrite existing draft`: replace the existing draft for that protocol
- `Fail if exists`: stop instead of changing anything

Skills are applied to the selected target bots from the embedded skill
documents. Identical skill content is idempotent. Different skill content is
shown in the review plan so the user can choose the correct target before
import.

Import does not automatically publish by default. Review and publish the
imported draft after confirming assignments, skills, artifacts, and stage text.

## Templates

Templates are user-authored protocol snapshots. They are managed inside
`Build -> Protocols`.

A template exists only after a user publishes a protocol and chooses
`Publish as template`. Copying a template creates a separate editable protocol.
It does not mutate the saved template.

## Text Documents

Protocol JSON/YAML import and export use the shared model in
`octopus_sdk/protocols/`.

Do not add a browser-only format, Telegram-only format, or script-only format.
Registry UI, registry API, SDK helpers, and Telegram-facing protocol commands
must converge on the same model.

## Common Troubleshooting

| Symptom | Check |
| --- | --- |
| Cannot publish | Stage assignment, invalid artifact paths, missing transitions. |
| Run does not start | Published version exists, entry agent is execution-healthy, launch fields are valid. |
| Stage is stuck | Agent health, linked routed work, provider execution fault, stage timeout. |
| Artifact is missing | Producing stage completed, artifact path matches declaration, file exists in workspace. |
| Import is blocked | Required stage mappings or skill target mappings need a local bot. |
| Telegram and Registry disagree | Treat it as a product issue; both should use the same protocol service. |

For first-time setup, use [GETTING_STARTED.md](GETTING_STARTED.md). For
operating the stack, use [OPERATIONS.md](OPERATIONS.md). For Telegram commands,
use [TELEGRAM.md](TELEGRAM.md).
