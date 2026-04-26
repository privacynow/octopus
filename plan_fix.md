# Registry Product Plan

## Purpose

This is the single active plan for Registry UI/product cleanup. It replaces the
older accumulated plan and absorbs the useful content from `ui_issues.md`.

The goal is not visual polish. The product problem is information architecture
and lineage: runtime objects are exposed as peer products, generated/test data
dominates normal surfaces, and users cannot reliably follow work from intent to
execution to artifacts.

Do not create another active UI plan. New product findings go into this file
before broad audit or implementation claims continue.

## Current State

### Completed And Verified

- `P2.19`: SPA navigation now swaps the new route shell before awaiting async
  route readiness, preventing stale Safari content under a new URL.
- `P1.4`: `Approvals` is removed from default main nav. The route remains for
  deep links/operator access.
- `P4.15` and `P4.23`: stage creation allows a name-only unassigned draft step.
  Owner role and assignment are progressive fields.
- `P4.15`: add-stage clicks with an unfinished draft prompt the user to
  continue, move, or discard instead of silently resetting draft data.
- `P4.26`: stage Assignment supports `New capability needed` through the
  existing skill/capability selector pipeline, not a duplicate runtime selector.
- `P4.26`: existing template capabilities that are not currently advertised by
  a live agent remain `Existing capability`. New-capability state is explicit
  author intent, not inferred from a catalog miss.
- `P4.26`: explicit Assignment mode changes remain explicit. A skill assignment
  can still be viewed through `Specific agent` mode when the author chooses it.
- `P4.25`: Capabilities defaults to a human catalog rather than a bot-management
  dead end.
- `P4.25`: Capabilities hides `*`, `Rehearsal`, and generated timestamp variants
  from the default catalog; rows are clickable and show assignment details.
- `P4.25`: default Capabilities now uses the same inline expand/collapse grammar
  as the other work surfaces. Selecting a capability expands details under that
  row, not in a side editor, and loads the real advertised instruction text from
  the existing bot skill-detail API.
- `P4.25` and `P5.11`: agent-scoped Capabilities now follows the same inline
  expansion grammar as the default catalog. The agent detail page routes into
  the shared Capabilities workspace instead of opening a duplicate drawer, and
  selected capability details render full-width below the clicked row rather
  than as a desktop side card.
- `P5.11`: the Agents list now expands agent details inline under the selected
  row, exposes `Open agent workspace` and `Open capabilities`, and removes the
  old detail-navigation/split-panel expectation from the default path.
- `P1.7`: default nav now uses Work, Build, Operations; operational
  `Dashboard` lives under Operations; fake `Team` is gone. Agents are moving
  into Work as collaborators/workers rather than remaining a Build resource.
- `P5.12`: Conversations pagination is visible, URL-addressable, refresh-stable,
  and verified in real Safari.
- Conversation task-thread copy now uses delegation/linked-work language while
  preserving the underlying task/delegation route.
- `P3`: Dashboard empty approvals collapse; the main backlog card routes to
  Runs; default dashboard language uses `Work needing attention`.
- `P1.6`, `P3.14`, `P4.24`, `P5.10`: generated/rehearsal/test records now use
  one shared default-visibility predicate. Conversations, Runs, Agents,
  Dashboard, Capabilities agent eligibility, Delegations, and the Protocol
  catalog hide those records by default and expose explicit audit/generated
  toggles where a user may need to inspect them.
- `P5.10`: Conversations now default to direct conversations instead of `All`;
  protocol-generated delegation threads remain available through the
  `Delegation threads`/`All` filters and generated/audit toggle.
- `P1.5`: `/ui/tasks` is reframed as `Delegations` for standalone work. When
  opened with `protocol_run_id`, it becomes `Run stage tasks` and shows those
  tasks as children of that run instead of as peer work.
- `P4.24`: Protocols default to canonical human-authored definitions; generated
  drafts are available through `Show generated drafts` and remain compacted in
  generated families when shown.
- `P4.24`: Default generated-record detection now covers timestamped protocol
  names, numeric template-derived variants such as `software-engineering-draft-69`,
  and anonymous `draft-<hash>` records.
- `P3.14`: Dashboard work groups exclude protocol-generated stage tasks from
  standalone work needing attention; protocol issues and runs remain the
  canonical protocol-execution surfaces.
- `P4`: software-engineering rehearsal testing now waits for the backend's
  pending rehearsal session before each UI response, preventing stale DOM
  session submissions.
- `P4.28`: rehearsal pending sessions are recoverable from persisted protocol
  run and routed-task state, and submit now re-enrolls once if the reserved
  rehearsal agent token was rotated by another registry process before the
  author answers a stage. The UI no longer depends only on the rehearsal
  manager's in-memory `_pending` map or a stale plaintext token.
- `P3.8`: Runs Overview is progressive again. It now shows run summary,
  current-step/artifact entry points, and available actions without rendering
  full stage evidence under Overview.
- `P3.14`: Runs use the existing cursor paginator instead of dumping the first
  50 executions into a single page.
- `P3.15`: Protocols first paint no longer blocks on the assignment catalog;
  template discovery now uses `GET /v1/protocol-templates`, authoring options
  use `GET /v1/protocol-authoring/options`, and the protocol catalog filters
  and paginates in SQL with catalog/template indexes.
- `P3.16`: Runs now filter/page in SQL before review-state decoration, protocol
  issues only scan candidate runs/stages, Dashboard renders a primary snapshot
  before secondary panels, and Conversation detail loads linked runs separately
  from the full protocol-launch catalog.
- `P3.17`: Dashboard secondary loading now degrades with per-call fallbacks and
  warning-level diagnostics instead of turning route/test teardown races into
  user-visible errors.
- `P3.18`: The data-analysis UI scenario now matches deployed five-stage agent
  execution time and verifies final run artifacts plus stage-task artifact
  preview after completion.
- `P4.27`: Conversation protocol management now renders the protocols panel and
  loads the published protocol catalog when Protocols is selected, even if
  linked protocol runs were already lazy-loaded.
- `P5.13`: Browser conversation message-send timeline verification is green
  after background dashboard work was made non-disruptive.
- `P3.14`: Usage now uses the shared generated/audit visibility predicate and
  exposes `Show generated/audit usage`; default usage totals/table are computed
  from visible human rows.
- `P3.14`: Usage rows now carry conversation lineage from the existing usage
  endpoint so protocol-stage task threads can be hidden from default usage
  without relying only on title heuristics.
- `P3.14`: The shared generated/audit predicate now covers generated workflow
  keys such as `compose-assistant-protocol` and `publish-report`, not only
  timestamped names.
- `P4.25`: Capability names now use the shared generated/rehearsal predicate, so
  generated/meta E2E capabilities do not appear in the default catalog.
- `P4.25`: the custom capability create dialog now uses labeled fields and
  initial focus instead of placeholder-only inputs, so UI automation and real
  users target the slug and description fields unambiguously.
- `P4`: the meta-assistant scenario now creates one stable human-facing
  capability (`assistant-workflow-composer-demo`) instead of generating new
  hidden E2E capability names that pollute or disappear from the default
  catalog.
- `P3.12` and `P6.4`: artifact rows with Preview/Open/Download/Copy actions no
  longer expose the entire artifact card as a single accessibility button; the
  row text remains the row action and artifact actions remain separate controls.
- `P5.1` and `P6.4`: the artifact-row accessibility fix exposed a follow-up
  regression where normal list rows with static trailing badges only responded
  on the text column. The shared row helper now reserves split pressable/action
  behavior only for rows whose trailing content actually contains controls.
- `B5` and `P1.5`: real Safari found that stage-task conversation rows expanded
  but showed `No protocol runs linked to this conversation yet` because the
  preview only queried `root_conversation_id`. The shared API client now
  resolves task-thread conversations through `external_conversation_ref` ->
  routed task -> `protocol_run_id`, and both conversation list and detail use
  that same path.
- `B5` and `P5.12`: real Safari then exposed a second linked-work gap:
  a direct `/ui/conversations?...&conversation_id=...` link could point to a
  conversation outside the current cursor page, leaving the URL selected but no
  row expanded. The conversation list now restores the selected conversation
  through the existing conversation API before rendering the page.
- `B5` and `P1.5`: real Safari on deployed commit `56af5bc` verified the
  full drill-through route: direct delegation-thread conversation link ->
  linked run -> run artifact preview -> stage evidence -> stage task -> task
  artifact preview.

Verified current state:

- `node --check` on edited JS files was clean.
- `git diff --check` was clean.
- `tests/e2e/playwright/protocol-ui.spec.js`: 14 passed against deployed
  registry commit `56af5bc`.
- `tests/e2e/playwright/registry-work-surface.spec.js`: 8 passed and 1 skipped
  against deployed registry commit `56af5bc`; the skipped task-detail test
  still requires a run with at least two routed stage tasks in the current data
  set.
- `tests/test_registry_ui_contract.py`: 41 passed locally after contract updates.
- `tests/test_registry_usage.py` plus
  `tests/test_registry_service.py::test_usage_endpoint_rolls_up_delegated_child_usage`
  passed locally after usage lineage updates.
- `tests/test_protocol_rehearsal.py`: passed locally after the rehearsal
  session and explicit artifact-content checks.
- Real Safari confirmed hard-refresh discipline, Capabilities filtering/detail,
  Work/Build/Operations nav, filtered Runs default, and conversation pagination
  Previous/Next/cursor behavior.
- Real Safari on deployed commit `b086911` confirmed default Runs hide
  generated/audit executions until the explicit toggle and verified run
  artifact drill-through to preview/copy actions before the accessibility patch.
- Real Safari on deployed commit `54dd3cb` confirmed hard refresh, run artifact
  rows expose Preview/Open/Download/Copy as separate controls, Preview renders
  real CSV artifact content, and delegation-thread conversation rows expand and
  collapse from the full row after the static-trailing-badge regression fix.
- Real Safari on deployed commit `56af5bc` confirmed the direct
  `conversation_id` route restores the selected row across pagination, resolves
  its linked protocol run after async task lookup, and preserves artifact
  Preview/Open/Download/Copy actions on both run and stage-task surfaces.
- Real Safari on deployed commit `4d16b22c` confirmed the Capabilities default
  catalog has no side-panel editor, expands Architecture inline with real
  instruction text, collapses from the same row, and reopens with URL state
  restored after `Option+Command+R`.
- `tests/e2e/playwright/registry-work-surface.spec.js`: 8 passed and 1 skipped
  against deployed registry commit `4d16b22c`, including the Capabilities
  inline-detail, collapse, and instruction-preview regression.
- Real Safari on deployed commit `15e08eb6` confirmed the agent-specific
  Capabilities page hard-refreshes into a stacked catalog, expands Architecture
  as a full-width panel below the row with real instruction text, and collapses
  from the same row. This closes the follow-up miss where the DOM was inline but
  desktop CSS still placed the detail as a right-side card.
- `tests/e2e/playwright/registry-work-surface.spec.js`: 9 passed and 1 skipped
  against deployed registry commit `15e08eb6`. The suite now asserts selected
  capability details are geometrically below the clicked row and nearly
  full-width, so the right-side card regression fails automatically.

### Pending Local Patch

The local patch now includes the deployed SDK/Telegram protocol-interface work
plus rehearsal-session recovery fixes found by the full deployed UI suite. The
latest local addition handles stale rehearsal agent tokens by re-enrolling once
on submit; it is awaiting redeploy and rerun of the failing data-analysis
rehearsal scenario before `P8` and `P4.28` can be marked fully verified. The
only unrelated untracked local item is `.cursor/`, which is not part of this
plan.

### Deployment Blocker

Octopus redeploy restarts registry, M1, and M2. M3 still fails because
`/Users/tinker/octopus/.deploy/provider-auth/claude/.claude.json` is zero bytes
and the M3 container exits with `Claude auth not found`.

The current execution excludes M3 per user direction. Do not claim full
M1/M2/M3 verification until M3 auth is restored; M1/M2 registry UI fixes remain
in scope.

## Product Model

### Protocol Surface Ownership

The Registry is the protocol control plane. It owns canonical HTTP APIs,
persistence, validation, permissions, lifecycle, templates, runs, artifacts,
human collaboration, and the Registry UI.

The bot SDK must not own duplicate protocol APIs or storage. It owns the shared
client/service interface that all bot channels use to call Registry protocol
APIs consistently.

Telegram, Slack, future bots, and Registry-adjacent clients are peer product
surfaces over the same Registry protocol model. Channel code should parse input
and render channel-native output, but protocol listing, launch, status, action,
artifact, and export semantics must come from the shared SDK interface.

Current smell:

- Registry APIs are in the correct place.
- `octopus_sdk.registry.client.RegistryClient` already wraps many protocol
  endpoints.
- `octopus_sdk.protocols.launch` already contains shared launch helpers.
- Telegram still hand-assembles parts of protocol start/status/action behavior
  in `app/runtime/telegram_ingress.py` and `app/runtime/telegram_protocols.py`.

Target:

- One SDK protocol service/client wraps the existing Registry client and launch
  helpers.
- Registry UI and Telegram both exercise the same canonical REST nouns.
- Telegram exposes the workflow-useful subset of Registry protocol capability,
  without becoming a protocol authoring UI.

### Work

Work is where users resume or inspect active work. It should answer:

- What needs attention?
- What is running?
- What completed?
- Where are the outputs?
- What do I do next?

Work should include:

- Conversations
- Runs / Executions
- Agents, as collaborators/workers users can start work with and inspect
- Delegations, if standalone delegated work remains a normal user destination

Work should not include:

- Empty queues
- Runtime health dashboards
- Raw routing diagnostics
- Provider guidance
- Duplicate protocol-stage task lists

### Build

Build is where users define things that can be reused.

Build should include:

- Protocols
- Capabilities

`Team` is not currently a real product category. Agents are not a team model in
this product. The normal Agents entry point belongs in Work because users talk
to agents, assign work to them, and inspect what they are doing. Agent
configuration, capability installation, provider setup, routing, and diagnostic
details should remain progressively disclosed inside the agent page or
Operations, not as the primary navigation model.

Templates are not a separate Build destination. They are protocol utilities:
users create a new protocol from a reusable starter or publish an existing
protocol as a reusable starter from inside the Protocols workflow.

### Operations

Operations is where platform/runtime concerns live.

Operations should include:

- Dashboard, unless it is redesigned into a true human Home
- Routing
- Usage
- Guidance
- Runtime diagnostics
- Provider auth/status
- Worker/capacity/trust/token controls
- Generated/test/rehearsal audit filters

The current Dashboard contains queues, health, usage, and protocol issues. In
that form it is operational, not normal Work.

### Delegations And Tasks

`Task` is a valid underlying concept: a delegation from one agent/person to
another. It exists even without protocols.

The mistake is treating all tasks the same in the UI:

- Standalone delegated work can be a normal product surface, likely named
  `Delegations`.
- Protocol-generated stage tasks are children of `run -> stage -> task`.
- Protocol stage tasks must not masquerade as independent peer work beside
  protocol runs.
- `/ui/tasks` may remain as the route during migration, but normal UI must show
  provenance clearly.

### Runs

Runs are protocol executions. A run owns:

- Stage order
- Stage execution state
- Protocol-generated tasks
- Conversations created for stage work
- Artifacts
- Decisions/review loops
- Issues and audit trail

Runs are the canonical surface for protocol execution.

### Protocols And Templates

Protocols are the canonical home for authoring, publishing, running, and
reusing workflows.

Templates are separate reusable starter objects, but they are managed through
Protocols rather than through a standalone gallery destination:

- `New protocol` offers `Blank protocol` and `From template`.
- `From template` shows built-in starters and team-published templates inline
  inside the Protocols creation flow.
- `Publish as template` copies a stable protocol snapshot into a separate
  template record.
- Templates do not live-reference mutable protocol drafts or silently change
  when the source protocol is edited later.
- Updating an existing template is explicit: `Update template from this version`
  or equivalent.
- `/ui/templates` and `/ui/gallery` are not product routes. Users enter
  templates from Protocols, and old template/gallery URLs should fall through
  to normal route recovery rather than acting as a second product surface.

### Conversations

Conversations are collaboration surfaces. They should not look empty when work
exists elsewhere.

Conversation pages must show:

- Chat timeline when there are messages
- Linked work when the useful content is tasks/runs
- Protocol launches and resulting run/artifact state
- Delegations in context

The normal UI should avoid making users choose a separate `Tasks` product from a
conversation unless the copy makes the relationship explicit.

### Capabilities

Capabilities are the human-facing concept. Skills, routing skills, selector
preview, advertised skills, and worker diagnostics are implementation or
operator vocabulary.

Default Capabilities should:

- Show searchable human capabilities without choosing a bot first
- Hide internal/system selectors such as `*` and `Rehearsal`
- Collapse generated timestamp variants
- Allow row click to inspect usage and assignment slug
- Offer bot-scoped install/import/draft/review only as secondary management

### Artifacts

Artifacts are concrete outputs. Every artifact reference should use one shared
action contract:

- Preview when previewable
- Open when host path/link is available
- Download when content is available
- Copy path/reference
- Clear unavailable state when a declared artifact has not been produced

This contract applies in Runs, Stages, Tasks/Delegations, Conversations, and
Dashboard references.

## Hard Rules

- The default UI must show human workflows, not implementation tables.
- Top-level navigation must be small enough to learn.
- A thing should have one canonical user-facing home.
- Deep links may exist for diagnostics, but should not force top-level clutter.
- Creating a draft object must not require execution-ready configuration.
- Assignment is progressive and should not block stage creation.
- Draft data must never be lost by switching tabs, panels, stages, or add-step
  anchors.
- Operator controls live in Operations or explicit technical details, not
  default authoring or work review.
- Generated/rehearsal/test data must not dominate default user surfaces.
- No database seeding may substitute for UI-created state during product
  verification.

## Target Navigation

This is the target structure. It is not fully implemented yet.

### Work

- Conversations
- Runs / Executions
- Agents
- Delegations, if standalone delegated work remains a normal user destination

### Build

- Protocols
- Capabilities

### Operations

- Dashboard, unless redesigned as a user Home
- Routing
- Usage
- Guidance
- Diagnostics/Admin

Open IA decisions:

- Final label: `Runs`, `Executions`, or `Work`.
- Whether standalone delegated work is visible as `Delegations` in default nav.
- Whether Dashboard moves to Operations or is split into `Home` plus
  `Operations Dashboard`.
- Exact wording for protocol starters: `Templates`, `Starters`, or
  `Reusable starters` inside the Protocols creation flow.

## Active Blockers

| ID | Blocker | Current Evidence | Required Outcome |
|----|---------|------------------|------------------|
| B1 | Tasks vs Runs needed lineage separation. | Done: standalone `/ui/tasks` is Delegations; `protocol_run_id` deep links are Run stage tasks; Dashboard excludes protocol stage tasks from standalone groups; real Safari verified Conversation -> linked run -> stage task -> artifact preview on deployed commit `56af5bc`. | Keep regression coverage in work-surface and protocol UI suites. |
| B2 | M3 cannot start. | Claude auth file is zero bytes; container exits. User explicitly excluded M3 from this execution. | Do not claim all-agent verification until M3 auth is restored. |
| B3 | Generated/rehearsal/test data dominated default pages. | Patched through shared visibility predicate across default pages with audit/generated toggles; Runs, Conversations, Protocols, Dashboard, Delegations, Agents, Capabilities, and Usage are covered by automated checks; Runs filtering was rechecked in real Safari after deploy. | Keep as regression coverage and include the same forbidden-data checks in the broad audit. |
| B4 | Protocol catalog was flooded by generated drafts. | Done for default catalog: real Safari shows only canonical drafts until `Show generated drafts`. | Keep regression coverage and revisit only if product needs a richer archive view. |
| B5 | Runs/Delegations/Artifacts lineage is still incomplete. | Done for the current product route: shared artifact action rows exist in Runs, Tasks, and task-board conversation context; Runs Overview links progressively into Stages and Artifacts; protocol E2E verifies run artifact preview/download and stage-task drill-through; real Safari verified direct conversation -> linked run -> run artifacts -> stage task -> task artifact preview on deployed commit `56af5bc`. | Keep as a regression gate and continue broader audit for other lineage surfaces. |

## Findings

### P1: Information Architecture

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P1.1 | Active | Sidebar exposes too many implementation nouns as peer destinations. | Real Safari nav review and DOM assertions. |
| P1.2 | Done | `/ui/templates` and `/ui/gallery` no longer exist as standalone destinations. | Templates removed from default nav; route contract asserts both route registrations are gone. |
| P1.3 | Active | Terminology drifts between Capabilities, skills, Templates, gallery, protocols, tasks, and runs. | User-facing string inventory. |
| P1.4 | Partial | Approvals is removed from default nav, but contextual approval verification remains. | Contextual approval scenario. |
| P1.5 | Done | Standalone delegations are real, protocol-generated stage tasks now have run-context copy, and direct task-thread `conversation_id` links stay visible across pagination. | Keep Safari and Playwright regression coverage for conversation linked work to run/stage task. |
| P1.6 | Done | Shared default visibility filtering is patched and covered across normal work/build/operations surfaces. | Keep broad-audit regression checks. |
| P1.7 | Planned | Dashboard is operational, Team is fake, and Agents belongs in Work as a collaborator/work entry point, with technical configuration progressively disclosed. | Nav grouping test plus real Safari pass after deploy. |

### P2: Platform Shell And Resilience

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P2.1 | Partial | 404 recovery exists but needs route smoke coverage. | `/ui/does-not-exist` recovery test. |
| P2.2 | Planned | Logout bypasses SPA intentionally but needs contributor contract. | Router contract test or note. |
| P2.3 | Planned | Sidebar resize behavior can surprise users. | Resize pass with open sidebar. |
| P2.6 | Planned | Session expiry/401 handling needs consistent return behavior. | Expired-session test. |
| P2.7 | Planned | CSRF bootstrap failure needs degraded state. | Forced CSRF failure test. |
| P2.8 | Planned | Offline/slow network can create duplicate toasts or endless loading. | Throttled/offline test. |
| P2.9 | Planned | WebSocket reconnect and route subscription lifecycle need verification. | Route-change/reconnect integration test. |
| P2.19 | Done | Real Safari stale SPA content after nav. | Playwright nav test plus Safari hard-refresh verification. |

### P3: Work, Runs, Delegations, Dashboard, Artifacts

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P3.1 | Active | Dashboard is an operational index, not a clean user Work surface. | Move/redesign Dashboard and assert nav placement. |
| P3.5 | Partial | Approvals empty queue was a dead top-level destination. | Default nav hides it; contextual approval still tested. |
| P3.8 | Partial | Expanded Runs now use Overview as a real entry point instead of rendering stage evidence by default; broad Safari verification still needed. | Progressive Overview/Stages/Artifacts/Audit tests. |
| P3.12 | Partial | Artifact actions use shared Preview/Open/Download/Copy behavior and row/action accessibility is fixed; remaining work is exhaustive cross-surface verification. | Shared artifact row tests in runs, stages, tasks, conversations. |
| P3.13 | Active | Stale leases can read as ordinary `running`. | Stuck-lease row and overview assertions. |
| P3.14 | Done | Default filtering is patched for Runs, Dashboard, Conversations, Agents, Protocols, Delegations, Capabilities, and Usage. | Real Safari broad-audit regression checks. |
| P3.15 | Done | Protocols render was blocked by full assignment/catalog loading and broad protocol scans. | Authoring options/templates API contract, SQL catalog indexes, protocol template Playwright flow. |
| P3.16 | Done | Runs and protocol issues fetch/page candidate rows before expensive decoration; Dashboard and conversation detail have progressive first-paint/lazy-loading paths. | SQL pagination/index tests, dashboard/nav Playwright, conversation linked-runs/protocol-panel smoke. |
| P3.17 | Done | Dashboard secondary loading no longer turns background navigation/teardown races into user-visible errors or failing console-error assertions. | Deployed Playwright rerun has zero dashboard secondary snapshot console errors. |
| P3.18 | Done | Real multi-stage protocol execution can outlive a short UI scenario budget even when it completes correctly and produces artifacts. | Deployed data-analysis scenario passed, including five-stage execution, run artifacts, and task artifact preview. |

### P4: Protocol Authoring, Protocol Catalog, Capabilities

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P4.6 | Partial | Workflow map must remain on-demand and interactive without replacing primary authoring. | Map interaction test. |
| P4.15 | Done | Create-stage flow blocked on assignment and could clobber draft data. | UI-only unassigned stage and draft-preservation tests. |
| P4.16 | Partial | Standard/operator authoring split must omit internals from standard DOM and API. | Negative tests for Advanced/custom runtime/internal fields. |
| P4.23 | Done | Blank stage required owner role. | Name-only stage creation test. |
| P4.24 | Done | Protocol list hides generated drafts by default and exposes compact generated families through a toggle. | Real Safari catalog verification passed on deployed `d2ac48a`. |
| P4.25 | Done | Capabilities must be a human catalog, not passive bot admin or internal selector list; generated/meta E2E capabilities are hidden by default; selected capabilities expand inline with real instruction content on both default and agent-scoped pages. | Row expand/collapse, geometry-below-row, instruction-preview, internal-filter, selector consistency tests, and real Safari pass on deployed `15e08eb6`. |
| P4.26 | Done | Missing capability had no natural assignment path. | `New capability needed` UI-only scenario. |
| P4.27 | Done | Conversation protocol management could show capabilities copy in a protocols-mode shell if linked runs were already loaded but the published protocol catalog was still lazy. | Deployed conversation protocol launch E2E opens the protocols body, lists published protocols, and launches a run. |
| P4.28 | Active | Data-analysis rehearsal found that a valid persisted stage task can still be rejected as `PROTOCOL_REHEARSAL_SESSION_NOT_FOUND` when either the in-memory pending session is missing or the reserved rehearsal agent token was rotated before submit. | Rehydrate pending rehearsal sessions from persisted run/task state, retry submit once after rehearsal-agent re-enrollment, then rerun focused rehearsal regression and deployed data-analysis Playwright scenario. |

### P5: Conversations, Agents, Collaboration

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P5.1 | Active | Conversation list filters and quick starts are busy, especially on mobile. | Filter-collapse/mobile smoke test. |
| P5.3 | Active | Conversation detail needs dedicated audit for composer, timeline, linked work, settings, focus, scroll, send/WS, markdown. | Dedicated conversation detail audit. |
| P5.10 | Done | Conversation list filters generated/rehearsal records by default and keeps audit access explicit. | Human conversations prioritized in real Safari. |
| P5.11 | Partial | Agent list and Capabilities agent eligibility hide generated/rehearsal agents by default; list details now expand inline and route to the shared Capabilities workspace; the remaining work is the broader agent-detail work-first audit. | Agent inline-detail tests, shared Capabilities route tests, and remaining work-first audit. |
| P5.12 | Done | Conversations pagination is broken or unclear. | URL-addressable pagination, Playwright pass, and real Safari pass after deploy. |
| P5.13 | Done | Conversation message-send timeline verification stays green after background dashboard work is made non-disruptive. | Deployed browser conversation send E2E returns to the visible chat timeline without console errors. |

### P6: Presentation, Accessibility, Responsive

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P6.1 | Planned | Breakpoints can create layout jumps. | Breakpoint review. |
| P6.3 | Planned | Protocol full rerender can cause keyboard/AT focus loss. | Keyboard focus preservation test. |
| P6.4 | Partial | Artifact action buttons are no longer nested under a single row button; broader ARIA verification remains. | Axe and manual keyboard pass. |
| P6.5 | Planned | Theme contrast is not systematically measured. | Light/dark contrast audit. |
| P6.11 | Planned | Mobile matrix is incomplete. | Mobile route matrix. |
| P6.12 | Planned | IA success metrics are undefined. | Define clicks/time-to-output measures. |

### P7: Operations And Admin Framing

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P7.1 | Active | Routing exposes powerful disable toggles with little framing. | Operations-only route and warning/context copy. |
| P7.2 | Active | Usage belongs in Operations with cost/token framing. | Operations nav and copy review. |
| P7.3 | Active | Guidance is provider/bot baseline editing and should remain Operations/admin. | Route framing and role/capability gate. |
| P7.4 | Planned | Multi-tenant/role model is assumed, not fully defined. | Product role/capability policy. |
| P7.5 | Planned | Security beyond CSRF/session needs a dedicated pass. | Markdown/XSS and approval-action review. |

### P8: SDK And Channel Protocol Surface

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P8.1 | Active | Protocol API ownership is correct in Registry, but channel integrations need one SDK protocol service/client instead of hand-assembling workflows. | SDK unit tests prove Telegram and future channels call the shared service over existing Registry client methods. |
| P8.2 | Active | Telegram supports protocol commands, but start/status/action/watch logic is still mixed into Telegram ingress helpers. | Telegram command tests assert parsing/rendering stays in Telegram while protocol semantics come from SDK service. |
| P8.3 | Active | Telegram can start and watch protocols but does not expose artifact discovery/download/preview parity with Registry UI. | `/protocol artifacts <run_id>` and optional export tests over generated run artifacts. |
| P8.4 | Active | Registry UI protocol launch and Telegram protocol launch need cross-surface equivalence. | Integration test starts equivalent runs from UI and Telegram/stub and asserts origin, root conversation, entry agent, run state, and artifact visibility. |
| P8.5 | Active | Stale protocol-authoring nouns such as `/v1/protocol-authoring/manifest` must not re-enter the product surface. | OpenAPI/SDK/UI contract test asserts current nouns and either intentional 404 or explicit deprecation for stale routes. |
| P8.6 | Planned | Telegram should expose only workflow-useful protocol operations, not full authoring/template/rehearsal/admin flows. | Telegram user-guide and presenter tests match the capability exposure table. |

## Workstreams

### W1: Navigation And Product IA

Scope:

- Remove fake `Team`.
- Move `Agents` into Work as the normal collaborator/work entry point.
- Keep agent technical configuration and operations controls progressively
  disclosed inside agent detail or Operations.
- Move current Dashboard into Operations or split it into Home plus Operations
  Dashboard.
- Decide if default nav exposes `Delegations`.
- Keep deep links for `/ui/tasks` and `/ui/approvals`.

Acceptance:

- Default nav expresses Work, Build, Operations.
- Work includes Agents; Build does not list Agents as a peer to Protocols and
  Capabilities.
- No normal user has to infer whether Tasks or Runs is the right place for a
  protocol execution.
- No important direct delegation workflow is lost.

### W2: Capabilities And Agents

Scope:

- Keep the Capabilities row click/detail/internal-filter behavior as a
  regression gate.
- Hide internal/system capabilities from normal catalog.
- Keep bot management secondary.
- Make agent pages work-first: start conversation, run protocol, current/recent
  work, availability, then capabilities/configuration as secondary detail.
- Group or hide Rehearsal/test agents from default normal views.

Acceptance:

- Capabilities opens to a usable catalog.
- Clicking Architecture or another capability expands meaningful details inline,
  including real instruction text from an advertising bot.
- Agent-specific Capabilities uses the same full-width row expansion and
  collapse behavior; it must not reintroduce a side drawer or desktop split
  editor for capability details.
- No `*`, `Rehearsal`, or generated timestamp flood in default catalog.
- Agent pages do not dump capabilities twice.

### W3: Conversations

Scope:

- Fix conversation pagination.
- Reframe `Tasks` view/copy as linked work or delegated work.
- Preserve task/delegation concept without making protocol stage tasks peer
  work.
- Ensure conversation-launched protocols are traceable to runs and artifacts.
- Make task-linked conversations non-empty by default.

Acceptance:

- Pagination controls work in real Safari and Playwright.
- Filters and selected inline detail survive pagination correctly.
- A conversation with linked run/task activity shows useful work context.

### W4: Runs, Delegations, And Artifacts

Scope:

- Tighten run expanded detail around Overview, Stages, Artifacts, Audit.
- Surface artifacts from Overview and stage context.
- Clearly mark stale leases and blocked states.
- Show protocol-generated tasks under run/stage lineage.
- Preserve standalone delegations separately.
- Push run list filtering, pagination, and common UI filters into SQL before
  decorating rows with review state.
- Push protocol-issue filters into SQL and only scan candidate runs/stages.
- Add indexes for run filters used by Runs, Conversations, Dashboard, and
  protocol launch drill-through.

Acceptance:

- A user can explain a run state from row and Overview.
- A user can preview/download artifacts from every context where they appear.
- Protocol stage task evidence does not require choosing a separate peer app.
- Run and issue pages stay responsive with large history because they page
  before expensive decoration.

### W5: Protocol Authoring And Catalog

Scope:

- Keep completed unassigned-stage and missing-capability flows green.
- Preserve interactive workflow map on demand.
- Group/hide generated protocol variants.
- Remove Templates/Gallery as a standalone product surface.
- Move template selection into the existing Protocols creation flow.
- Add `Publish as template` from a protocol as a snapshot-copy operation, not a
  live reference to a mutable draft.
- Add explicit template update semantics for future edits.

Implementation guidance:

- Reuse the existing protocol editor and draft creation pipeline.
- Extend the current `source_kind: "template"` creation path instead of adding a
  parallel template editor.
- Add one backend template object/snapshot path for user-published templates
  while preserving built-in starters as system-provided template records.
- The template list API should return built-in starters plus user/team-published
  templates for the current authoring context.
- Publishing a template should copy from a published protocol version by
  default. Draft-to-template, if allowed, must be explicit and validated.
- Do not let source protocol edits mutate existing templates silently.
- Do not reintroduce `/ui/templates` or `/ui/gallery`; normal nav and CTAs
  should point at `/ui/protocols` creation.

Acceptance:

- Blank-to-published protocol authoring is possible through UI only.
- Protocol-to-template publishing is possible through UI only.
- Creating from a template is available inside Protocols, not a separate gallery.
- A template created from a protocol remains stable after later source protocol
  edits.
- Updating a template from a protocol is explicit and auditable.
- Stage add/remove/assignment/routing/artifact flows are verified.
- Protocol list prioritizes canonical workflows.

### W6: Operations, Resilience, Accessibility

Scope:

- Route Operations concerns out of normal Work/Build.
- Verify session/CSRF/offline/WS behavior.
- Run accessibility, keyboard, contrast, reduced-motion, and mobile matrix.
- Keep Safari cache refresh discipline after deploy.

Acceptance:

- Operator controls are framed and gated.
- Browser resilience does not create stale or misleading UI.
- UI is usable in keyboard, mobile, and light/dark modes.

### W7: Responsiveness And Loading Model

Scope:

- First paint should render useful shell/primary rows without waiting for
  secondary catalog, preview, or management data.
- Heavy list endpoints should filter and paginate in SQL before Python
  decoration or access-safe post-processing.
- Secondary panels should use lazy loading and cache/stale-while-revalidate
  behavior where the data is not needed for the initial user decision.
- Do not add duplicate endpoints for the same product concept; rename or extend
  existing resources with clear nouns.

Acceptance:

- Protocols, Runs, Dashboard, and Conversation detail show useful content before
  enrichment data finishes.
- Dashboard first paint is not blocked by protocol catalog, run issue, or agent
  management calls.
- Conversation detail does not fetch the full published protocol catalog unless
  the protocol management panel is opened.
- Query plans have matching indexes for run filters and issue candidates.

### W8: SDK And Telegram Protocol Surface

Scope:

- Add one SDK protocol service/client over the existing `RegistryClient`
  protocol methods and `octopus_sdk.protocols.launch` helpers.
- Keep Registry HTTP APIs in Registry; do not move storage, validation,
  lifecycle, artifacts, or permissions into bot runtimes.
- Migrate Telegram protocol commands so command parsing and rendering remain in
  Telegram, while listing, launch, status, actions, artifacts, and export use
  the SDK protocol service.
- Keep Registry UI on canonical REST nouns and align JS API contracts with SDK
  endpoint coverage.
- Add Telegram artifact UX for protocol runs.
- Add cross-surface verification that Registry UI and Telegram start equivalent
  protocol runs and expose the same outputs.

Implementation guidance:

- Reuse `octopus_sdk.registry.client.RegistryClient` methods; do not add a
  second HTTP client or duplicate endpoint wrappers.
- Reuse `octopus_sdk.protocols.launch.launch_protocol_from_conversation` and
  existing protocol models.
- Put new product-level SDK behavior in an SDK module, not in
  `app/runtime/telegram_ingress.py`.
- Keep Telegram-specific session watch persistence in Telegram runtime code
  only where it is truly channel state.
- Use current registry nouns: `/v1/protocols`, `/v1/protocol-drafts`,
  `/v1/protocol-templates`, `/v1/protocol-authoring/options`,
  `/v1/protocol-runs`, and run artifact/action/export subresources.
- Do not revive `/v1/protocol-authoring/manifest` as a second authoring API.

Telegram capability exposure:

| Registry protocol capability | Telegram behavior |
|------------------------------|-------------------|
| List published protocols | `/protocol list` |
| Launch from conversation | `/protocol start <slug> <problem statement>` |
| View run status, stage, participants | `/protocol status <run_id>` |
| Watch/unwatch updates | `/protocol watch <run_id>` and `/protocol unwatch <run_id>` |
| Retry, accept, send back, cancel | Existing action commands, with confirmation for destructive actions |
| List run artifacts | Add `/protocol artifacts <run_id>` |
| Download/open artifact | Provide Registry links where safely available; clearly explain unavailable artifacts |
| Preview small text artifact | Optional short preview, capped and escaped for Telegram |
| Export run | Optional `/protocol export <run_id>` if output is sent as a document or concise link |
| Author/edit protocols | Registry UI only; Telegram links to Registry |
| Publish templates | Registry UI only |
| Rehearsal/scenario authoring | Registry UI only |
| Validate/publish/archive/diff | Registry UI or future operator-only command, not normal Telegram |

Acceptance:

- A user can discover, start, track, and inspect a protocol run from Telegram.
- Telegram artifact output is understandable: available, missing, declared, or
  unavailable-on-host states are explicit.
- Registry UI protocol launch and Telegram launch produce equivalent Registry
  run records and artifact visibility.
- Telegram code no longer owns protocol workflow semantics beyond channel
  parsing, rendering, and watch persistence.
- Future bot channels can adopt the same SDK protocol service without copying
  Telegram command internals.

## Immediate Execution Order

1. Implement the SDK protocol service/client over the existing Registry client
   and launch helpers.
2. Migrate Telegram `/protocol` commands to the SDK service without changing
   command syntax.
3. Add Telegram artifact UX and tests.
4. Add SDK, Telegram, Registry UI, and cross-surface equivalence tests.
5. Run dashboard, run, protocol, and Telegram smoke against the deployed
   registry/M1/M2 stack.
6. Hard-refresh real Safari for Registry UI verification.
7. Keep M3 excluded from current claims; do not block UI/SDK/Telegram cleanup
   on M3 auth.
8. Run accessibility, keyboard, mobile/narrow Safari, theme-contrast, and
   resilience checks.
9. Only then resume broad 500+ screenshot audit.

## Verification Matrix

| Command / Pass | What It Proves |
|----------------|----------------|
| `node --check` on edited JS | No syntax regressions in changed UI code. |
| `git diff --check` | No whitespace/patch hygiene issues. |
| `.venv/bin/python -m pytest tests/test_registry_ui_contract.py` | Static UI contracts match product terminology and shared primitives. |
| `.venv/bin/python -m pytest tests/test_protocols.py tests/test_db_postgres.py` | Protocol run/issue query behavior and DB indexes remain valid. |
| `.venv/bin/python -m pytest tests/test_registry_sdk_contract.py tests/test_sdk_type_safety.py` | SDK contracts and type boundaries remain valid. |
| `.venv/bin/python -m pytest tests/test_protocol_telegram.py tests/test_telegram_presenters.py` | Telegram protocol commands and rendered messages use the shared protocol interface correctly. |
| `.venv/bin/python -m pytest tests/test_telegram_runtime_skills.py tests/test_telegram_delegation_channel.py` | Telegram regressions around skills and delegation still hold after protocol-service migration. |
| Telegram API stub protocol pass | Bot surface can list/start/status/watch/artifacts/export protocols against a running Registry without direct DB setup. |
| `./.tmp/playwright/node_modules/.bin/playwright test -c tests/e2e/playwright.config.js tests/e2e/playwright/protocol-ui.spec.js` | Protocol authoring, rehearsal, execution, conversations, and artifacts still work. |
| `./.tmp/playwright/node_modules/.bin/playwright test -c tests/e2e/playwright.config.js tests/e2e/playwright/registry-work-surface.spec.js` | Work/nav/runs/conversations/tasks/capabilities desktop behavior. |
| Cross-surface protocol launch pass | Registry UI launch and Telegram launch create equivalent run lineage and artifact visibility. |
| Real Safari nav pass | Deployed assets, cache, and actual browser behavior match tests. |
| Real Safari Capabilities pass | Human catalog is clickable, filters internals, expands/collapses inline, and shows real instruction text without a side editor. |
| Real Safari Conversations pass | Pagination and linked work behavior are usable. |
| Full audit | Breadth after known blockers are fixed, not a substitute for scenario depth. |

## Route And Component Map

| Route | Component |
|-------|-----------|
| `/ui`, `/ui/` | `components/dashboard.js` |
| `/ui/approvals` | `components/approval-list.js` |
| `/ui/agents` | `components/agent-list.js` |
| `/ui/agents/:id` | `components/agent-detail.js` |
| `/ui/agents/:id/conversations` | `components/agent-detail.js` |
| `/ui/conversations` | `components/conversation-list.js` |
| `/ui/conversations/:id` | `components/conversation-detail.js` |
| `/ui/tasks` | `components/task-list.js` |
| `/ui/protocols` | `components/protocol-workspace.js` |
| `/ui/runs` | `components/protocol-workspace.js`, `renderProtocolRuns` |
| `/ui/routing` | `components/routing-policy-list.js` |
| `/ui/skills` | `components/skill-catalog.js` |
| `/ui/usage` | `components/usage-view.js` |
| `/ui/guidance` | `components/guidance-editor.js` |
| `/ui/login` | `components/login-form.js` |

Shared primitives:

- `helpers/ui.js`
- `helpers/kit.js`
- `components/task-board.js`
- `components/composer-autocomplete.js`
- `components/event-renderers.js`
- `router.js`
- `app.js`
- `ui/css/main.css`

## Definition Of Done

- Default nav reflects Work, Build, Operations without fake categories.
- Standalone delegations remain usable.
- Protocol-generated tasks are contextual children of runs/stages.
- Capabilities is a human catalog by default and bot management is secondary.
- Protocol authoring keeps unassigned, agent-only, capability-only, and missing
  capability flows green.
- Conversations pagination works and linked work is visible.
- Runs expose state, stage, task, conversation, artifact, and audit lineage in
  one coherent model.
- Artifacts use the same action contract everywhere.
- Protocol APIs remain canonical in Registry; bot SDK exposes one shared
  protocol service/client over those APIs.
- Telegram can list, launch, inspect, watch, act on, and inspect artifacts for
  protocol runs without duplicating protocol workflow semantics.
- Registry UI and Telegram protocol launches produce equivalent run lineage and
  artifact visibility.
- Generated/rehearsal/test data does not dominate normal user pages.
- M3 status is either fixed or explicitly excluded from real-agent claims.
- All listed automated checks pass after deploy.
- Real Safari is hard-refreshed and visually verified after deploy.

## Deployment Rule

For live verification:

1. Commit and push from `/Users/tinker/output/bots/telegram-agent-bot`.
2. Pull in `/Users/tinker/octopus`.
3. Redeploy from `/Users/tinker/octopus`.
4. Hard-refresh Safari with `Option+Command+R`.
5. Verify in real Safari before claiming product completion.
