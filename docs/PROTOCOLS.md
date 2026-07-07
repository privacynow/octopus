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
2. Choose `Auto protocol`, `Start blank`, or copy a user-authored template.
3. Name the protocol with a clear human title and stable slug.
4. Add stages in execution order.
5. Write stage instructions as the real work contract.
6. Configure each stage assignment.
7. Declare artifacts and attach stage inputs/outputs.
8. Configure transitions and review loops.
9. Validate.
10. Publish.
11. Start a run from the published version.

For serious work, do not collapse the workflow into one build stage. Put
planning, making, reviewing, and readiness evidence into separate stages. The
review stages are not ceremony: they give the protocol a way to reject weak
work, send it back with specific feedback, and record why the accepted output is
good enough.

Standard authoring should expose title, instructions, assignment, artifacts,
routing, validation, and run feedback. It should not expose raw runtime
selectors, raw stage keys, timeout fields, max-round internals, or custom
operator controls to normal authors.

## Auto Protocol

Auto Protocol is the fastest authoring path when the user knows the outcome but
does not want to manually design every stage.

From `Build -> Protocols`, choose `Auto protocol`, describe the desired outcome,
attach any source files that should inform the work, and add optional
constraints. Registry sends the design job to a connected provider-capable bot,
and immediately saves a durable `planning` session backed by a hidden
`auto_design` routed task. The dialog stays open, subscribes to the
`protocol-auto-session:{id}` update topic, and polls as a fallback while the bot
performs heavyweight semantic planning. The operator can leave and re-open the
dialog; the session re-attaches to the same planner job instead of starting a
duplicate one. When the routed task posts the typed planner result, Registry
compiles it into a normal editable protocol draft with inferred roles, stages,
artifacts, adversarial review loops, run inputs, resource references, and final
evidence.
Review the generated structure, ask for changes if needed, then apply it as a
normal draft. When validation and assignments are already ready, the Auto
Protocol panel can also publish or publish and run directly; otherwise use the
normal editor to resolve the warnings first.

Planner assignment is queue-based. `Auto` is the default and chooses among
connected agents that advertise `design_auto_protocol`, skipping agents already
busy with another Auto Protocol design when another capable agent is available.
Operators may explicitly target a planner agent from the dialog; invalid,
disconnected, or unsupported targets are rejected server-side.

Auto Protocol validates its generated draft before it shows it as ready. The
generator repairs structural issues such as missing slugs, missing artifact
declarations, missing participants, invalid transitions, and missing assignment
rules before the user sees the result. If the system still cannot produce a
valid protocol, the session is marked failed or blocked with the specific issue
instead of being presented as a runnable draft.

Auto Protocol can also revise an existing protocol. Open a draft or published
protocol and choose `Improve with Auto Protocol`. Drafts are changed only after
confirmation. Published versions are immutable; Auto Protocol prepares a draft
revision that affects only future runs after publish.

Auto Protocol can also improve from an existing run. Open `Work -> Runs`, select
the run, and choose `Improve this run`. Octopus includes the run objective,
status, primary artifact, produced artifacts, blocker reasons, runtime events,
review decisions, and structured run lessons as context, then creates a normal
Auto Protocol revision of the underlying protocol. This is the path to bring an
older run up to the current bar without manually patching the artifact.

The generated result is not a separate format. It is the same canonical
protocol document used by manual authoring, export/import, publish, and run
execution.

Attached files are normal Registry resources. The same resource record can be
used by Auto Protocol create/revise, manual run launch, improve-run, a Registry
conversation message, a direct assignment, or a Telegram upload. Receiving bots
get authorized resources as scoped input attachments through the SDK inbound
message path.

Auto Protocol is useful for serious workflows because it starts from the
requirement and infers the workflow shape. It should not blindly create one
generic sequence for every request. A game workflow may need creative,
historical, art, sound, implementation, playtest, UX, and release reviewers. An
analytics workflow may need data modeling, visualization, validation, and
readiness evidence. A simple workflow may need fewer stages.

For serious products, Auto Protocol now separates the planner's outline from
the authoritative acceptance contract. The planner stores only a v2 skeleton in
`metadata.auto_protocol.acceptance_contract`: product class, whether a full
contract is required, the `auto_protocol_contract` artifact key, and the
minimum evidence kinds. Early run stages then produce and review the real
run-specific contract as artifacts: product/domain first, then system and
verification. The gate reads the latest reviewed `auto_protocol_contract`
snapshot, not the planner's prose, before final acceptance. This is required for
runnable apps, APIs, dashboards, workflow engines, persistent-state systems,
external-provider integrations, finance/trading, payments, secrets, live
actions, recommendations, backtesting, or other high-risk product classes.

Generated workflows are budgeted. The normal compiler keeps the primary outcome
stage immediately before final acceptance and rejects plans above the hard stage
cap instead of silently creating a token-heavy workflow. The final stage is an
adversarial outcome acceptance gate: it inspects or exercises the primary
artifact and can return defective work to the outcome stage. Runtime contract
defects such as a missing, invalid, or non-run-ready manifest are converted into
an in-product revise transition when the protocol has a revise path; missing
operator exercise evidence remains blocked until the runtime is exercised.
For serious contract-backed products, generated stages also receive explicit
execution budgets in the stage runtime contract. Provider runtimes honor that
budget per stage, so heavyweight contract, implementation, and evidence stages
do not silently fall back to a short global bot timeout.

Every Auto Protocol declares primary artifact metadata. Runs UI and Telegram
promote that artifact first, then show supporting plans, reviews, and release
evidence below it. Users should not have to hunt through intermediate review
files to find the thing they asked Octopus to produce.

The default Runs page is recent-first for meaningful Registry and Telegram runs.
Use the view filters for attention, running, completed, outcome-bearing, or
surface-specific runs; use the generated/audit toggle only when inspecting
rehearsal, smoke, or internal generated records.

### Auto Protocol Verification

Treat Registry and Telegram as peer product surfaces for Auto Protocol. A
change is not done just because the SDK compiler and Registry panel work. The
same session lifecycle must be usable from Telegram without memorizing hidden
commands or copying raw ids between screens.

Minimum human verification:

1. Generate a protocol from Registry and inspect the summary, packages, stages,
   warnings, primary artifact, attached-resource count, and available actions.
   For large requirements, confirm the modal remains responsive while the
   session status is `planning` and then updates to ready, blocked, or failed
   without a browser request timeout.
2. Generate a protocol from Telegram with `/protocol auto <requirement>` and
   confirm the returned card is readable, explains the proposed workflow, shows
   the primary outcome, and offers obvious next actions.
3. Modify or re-open the Telegram session with visible controls or short
   follow-up commands shown in the message. A normal user should not need to
   remember a complex protocol command grammar.
4. Apply, publish, and run from the surface being tested when validation and
   assignments are ready, or show clear blockers and next steps when they are
   not ready.
5. Open the run and confirm the primary artifact is promoted before supporting
   plans, reviews, logs, and evidence.
6. Verify Registry desktop, Registry narrow, Telegram Web, and Telegram links in
   real Safari for UI-impacting changes.

If Registry and Telegram disagree about readiness, actions, warnings, stage
shape, or primary artifact prominence, treat that as a product defect rather
than a documentation issue.

## Review Loop Pattern

The highest-quality protocol runs usually have feedback loops.

Use this pattern when the output must be commercially usable, reviewed, or
shareable:

1. `Plan` stage: define the outcome, constraints, audience, artifacts, and
   acceptance bar.
2. `Review plan` stage: accept the plan or revise it before downstream work
   starts.
3. `Build/design/model` stage: create one meaningful artifact or decision
   package.
4. `Review` stage: inspect the produced artifact against the prior contract.
5. `Revise` transition: send weak work back to the stage that can fix it.
6. `Accept` transition: move forward only when the reviewer records why the
   work is sufficient.
7. `Readiness evidence` stage: summarize what was produced, what was checked,
   remaining risks, and next improvements.

For a simple two-agent setup, assign one agent as planner/reviewer and another
as maker/implementer. In a larger deployment, use specialized reviewer roles:
domain reviewer, data-model reviewer, security reviewer, UX reviewer, or final
acceptance reviewer. If only one execution-healthy agent exists, still keep the
review stages distinct so the run records the feedback and acceptance decisions.

Common transition shape:

| Stage kind | Decision | Next step |
| --- | --- | --- |
| Work stage | `completed` | Review stage |
| Review stage | `accept` | Next work stage |
| Review stage | `revise` | Prior work stage |
| Review stage | `fail` | Failed run or operator intervention |
| Final evidence stage | `completed` | Finish successfully |

Reviewer instructions should be concrete. Tell the reviewer what to accept, what
to reject, what artifact to write, and what decision words to use. Example:

```text
Accept only if the artifact is self-contained, readable, responsive, and meets
the declared acceptance criteria. Choose revise for missing outputs, vague
analysis, broken interactions, duplicate state, clipped text, or any dependency
outside the declared contract. End with PROTOCOL_DECISION: accept, revise, or
fail and PROTOCOL_SUMMARY.
```

The manufacturing example shows this pattern in practice:
[Manufacturing intelligence](examples/manufacturing-intelligence/README.md).

## Stages

Common stage kinds:

- `work`: an agent performs work
- `review`: a reviewer decides whether work should continue or be revised
- `acceptance`: final acceptance or rejection

Write stage instructions as if the assignee will only see that stage, its
declared inputs, run context, and the workflow contract. Avoid relying on a
human to restate artifact filenames or private implementation details at launch
time.

For review stages, write instructions like an acceptance test. A reviewer should
not merely summarize work; the reviewer should make a decision, explain it, and
route the run forward or back. This is how later attempts improve without a
human manually editing the artifact outside the protocol.

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

When a produced workspace artifact is observed, Octopus snapshots the available
file or directory into Registry-managed artifact storage. Users can also click
`Retain package` from the run artifact row. Content routes prefer the live
workspace path, then the retained package, then an honest unavailable state.
This lets authors clean bot workspaces without breaking important outcomes.

### Runnable artifacts

If the expected output is an interactive product, the protocol should make that
explicit. Examples include browser games, analytics SPAs, Java or Python
services, and risk engines with a UI over public APIs.

Runnable package artifacts should include `octopus-runtime.json` at the package
root. Static browser packages may also be recognized from a root `index.html`.
Process-backed packages should declare:

- `runtime_kind`: `node`, `python`, `java`, `binary`, or `process`
- `start_command`: the command the bot runtime runs inside the package
- `ui_path`, `health_path`, and `api_base_path`
- a docs endpoint
- smoke-test steps for reviewers
- an outcome-readiness matrix in release evidence, and preferably
  `metadata.outcome_readiness_checks` in the manifest for representative
  journeys or scenarios
- `test_hooks` when a protocol carries a structured acceptance contract

The `start_command` must launch an already prepared artifact. Registry rejects
process-backed runtime starts that try to install dependencies, build, package,
test, or use developer-mode commands. Build and smoke-test during the protocol
work stage, then launch with a cheap command such as `java -jar target/app.jar`,
a prebuilt binary, or an equivalent prepared app entry point. When Registry
rejects a non-run-ready start, the run detail keeps the runtime action available
and shows the product blocker so the next reviewer
or revise path has a concrete correction target.

Registry owns the user-facing URL, auth, status, and lifecycle. The bot runtime
owns the process. Users should be able to start/open the app, exercise the UI or
API, inspect logs/status, stop the runtime, and still download the artifact as a
zip package.

Generated artifacts should not use Octopus as their customer-facing brand unless
the user explicitly requested that. Octopus is the platform and runtime owner;
the customer-facing app title, dashboard, API name, examples, and help text
should use the user's brand or neutral domain-specific language.

Final acceptance for a runnable primary artifact is evidence-gated. If the
primary artifact declares `octopus-runtime.json`, Octopus expects runtime start
evidence, a healthy runtime check, user interaction through Registry routing, a
routed UI/API core-action fetch, visible-result evidence, an outcome-readiness
matrix, and a customer-facing branding check before the acceptance stage can
complete successfully. This keeps a reviewer from accepting a runnable system
only because files exist or one happy-path click worked.

The gate is product-owned. A human or chat operator can exercise the runtime,
but the final accept/block decision is made from Registry run state, transitions,
artifact evidence, and runtime events. Manifest policy is generic: process
runtimes must start prepared artifacts and may be rejected for dependency
install, build, package, test, or developer-mode commands; Maven is only one
example of that broader policy.

When a protocol version includes
`metadata.auto_protocol.acceptance_contract`, final acceptance uses structured
runtime evidence instead of prose-only claims. The contract names required
journeys in terms of stable hook ids. The artifact must expose those hooks in
`octopus-runtime.json.test_hooks`, typically as `data-testid` locators. Missing
or unmapped hooks are artifact contract failures. The bot-side journey runner
executes only Registry-routed artifact URLs, sends its scoped runtime token only
to the Registry origin, blocks arbitrary external navigation unless the
contract allows it, and posts structured pass/fail results back to Registry.
Journey results count only when they reference a Registry-issued
`journey_run_id` for the current runtime instance and retained artifact
snapshot. Producer and planning stages do not receive journey-result
capabilities; structured acceptance evidence must come from the acceptance
runner or an operator-requested re-run. Protocols without an acceptance contract
keep the legacy runtime/prose evidence gate.

The evidence manifest artifact keys are `producer_evidence_manifest` and
`reviewer_evidence_manifest`. They are normal protocol artifacts and are read
from the latest retained snapshot when the acceptance gate evaluates a
contract-bearing run. For v2 contracts, each evidence item also carries a trust
tier, source stage, observed time, current artifact content hash, runtime
instance when applicable, observed result, and corroboration references. Tier 1
evidence is machine-corroborated by Registry state: runtime start/health,
journey results tied to a Registry-issued `journey_run_id`, API probes matched
against server-generated fetch events, and retained snapshot hashes. Tier 2 is
independent reviewer attestation such as unit/integration tests, DB invariants,
provider mocks, state-machine checks, and security checks; it must be produced
by the expected reviewer or verification stage and match the current artifact
hash. Tier 3 is advisory evidence such as domain sources, live-provider notes,
and residual-risk explanations. Advisory evidence can be required for
visibility, but it cannot satisfy machine-proof requirements.

The v2 gate covers more than browser journeys. The reviewed
`auto_protocol_contract` must describe product workflows, unsafe actions,
domain assumptions and source boundaries, API surface, persistence/state
invariants, provider ports and callouts, secrets/auth boundaries, failure
behavior, positive and negative tests, backend/API probes, DB/state checks,
provider mock or live-status checks, browser journeys, and documentation checks
when the product needs them. A reviewer manifest that only says "looks good" or
contains uncorroborated JSON is not enough.

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
- `interrupt`
- `cancel`

Actions are permission-gated, version checked, and recorded in run history.
Corrective or destructive actions should require a reason where applicable.

`interrupt` stops the active stage from the operator side, marks the stage
blocked with `operator_interrupted`, and asks the assigned bot to cancel the
running provider subprocess when it can. The server rejects interrupt attempts
against terminal runs or completed stages with a conflict response; hiding the
button in the UI is not the correctness rule. `cancel` ends the whole run and
also requests provider cancellation when work is still running. Late provider
results after an interrupted, timed-out, blocked, or canceled stage are kept as
task/audit metadata only; they do not advance the run or overwrite artifact
records or retained snapshots.

When a stage issue says `Expired write lease`, it means the Registry has not
heard a lease-renewing task update before the lease expiry. It is not proof the
provider process died. Check task age, timeout, stage status, and latest task
update before retrying or interrupting.

## Fork And Resume

Runs can be forked from a selected stage when an operator wants to preserve
earlier work but continue as a separate run. A fork never mutates the parent
run. Octopus materializes retained snapshots into a new run-scoped workspace
prefix and records parent/child lineage on the run detail.

Fork modes:

- `Rerun selected`: copy snapshots before the selected stage, seed prior stage
  history, then dispatch the selected stage again.
- `Continue after`: copy snapshots through the selected stage, seed prior
  stage results, decisions, summaries, and previous feedback, then dispatch the
  next stage.

If required snapshots are missing, the fork is blocked with a list of missing
artifacts. Retain packages before cleanup when a run may need to be forked or
resumed later.

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

For first-time setup, use [GETTING_STARTED.md](GETTING_STARTED.md). For the
browser Registry workflow, use [USER_GUIDE.md](USER_GUIDE.md). For Telegram
commands, use [TELEGRAM.md](TELEGRAM.md). For operating the stack, use
[OPERATIONS.md](OPERATIONS.md).
