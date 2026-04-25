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
- `P1.7`: default nav now uses Work, Build, Operations; `Agents` lives under
  Build; operational `Dashboard` lives under Operations; fake `Team` is gone.
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
- `P3.8`: Runs Overview is progressive again. It now shows run summary,
  current-step/artifact entry points, and available actions without rendering
  full stage evidence under Overview.
- `P3.14`: Runs use the existing cursor paginator instead of dumping the first
  50 executions into a single page.
- `P3.14`: Usage now uses the shared generated/audit visibility predicate and
  exposes `Show generated/audit usage`; default usage totals/table are computed
  from visible human rows.
- `P4.25`: Capability names now use the shared generated/rehearsal predicate, so
  generated/meta E2E capabilities do not appear in the default catalog.

Verified current state:

- `node --check` on edited JS files was clean.
- `git diff --check` was clean.
- `tests/e2e/playwright/protocol-ui.spec.js`: 14 passed locally after the
  default-surface, rehearsal-session, Runs, Usage, and capability-filter fixes.
- `tests/e2e/playwright/registry-work-surface.spec.js`: 8 passed and 1 skipped
  locally after the Runs pagination/detail fixes; the skipped task-detail test
  requires a run with at least two routed stage tasks in the current data set.
- `tests/test_registry_ui_contract.py`: 41 passed locally after contract updates.
- Real Safari confirmed hard-refresh discipline, Capabilities filtering/detail,
  Work/Build/Operations nav, and conversation pagination Previous/Next/cursor
  behavior.
- Real Safari on deployed `d2ac48a` confirmed Conversations defaults to direct
  conversations, generated/audit work is restored only through the explicit
  toggle, Protocols defaults to the two canonical drafts, and generated protocol
  variants are hidden until `Show generated drafts`.

### Pending Local Patch

None at this point. The only untracked local item is `.cursor/`, which is not
part of this plan.

### Deployment Blocker

Octopus redeploy restarts registry, M1, and M2. M3 still fails because
`/Users/tinker/octopus/.deploy/provider-auth/claude/.claude.json` is zero bytes
and the M3 container exits with `Claude auth not found`.

The current execution excludes M3 per user direction. Do not claim full
M1/M2/M3 verification until M3 auth is restored; M1/M2 registry UI fixes remain
in scope.

## Product Model

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
- Templates, only if they stay as a focused starter surface
- Capabilities
- Agents, because users combine agents with capabilities and protocols

`Team` is not currently a real product category. Agents are not a team model in
this product; they are author/runtime resources.

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
- Delegations, if standalone delegated work remains a normal user destination

### Build

- Protocols
- Templates
- Capabilities
- Agents

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
- Whether `/ui/templates` remains separate or becomes a Protocols starter view.

## Active Blockers

| ID | Blocker | Current Evidence | Required Outcome |
|----|---------|------------------|------------------|
| B1 | Tasks vs Runs needed lineage separation. | Patched: standalone `/ui/tasks` is Delegations; `protocol_run_id` deep links are Run stage tasks; Dashboard excludes protocol stage tasks from standalone groups. | Deploy and Safari-audit the route from Conversation -> linked work -> run -> artifact. |
| B2 | M3 cannot start. | Claude auth file is zero bytes; container exits. User explicitly excluded M3 from this execution. | Do not claim all-agent verification until M3 auth is restored. |
| B3 | Generated/rehearsal/test data dominated default pages. | Patched through shared visibility predicate across default pages with audit/generated toggles; Conversations and Protocols verified in real Safari. | Finish real Safari checks for Runs, Dashboard, Delegations, and Capabilities after the next broad audit pass. |
| B4 | Protocol catalog was flooded by generated drafts. | Done for default catalog: real Safari shows only canonical drafts until `Show generated drafts`. | Keep regression coverage and revisit only if product needs a richer archive view. |
| B5 | Runs/Delegations/Artifacts lineage is still incomplete. | Shared artifact action rows already exist in Runs, Tasks, and task-board conversation context; Runs Overview now links progressively into Stages and Artifacts. | Complete run/conversation/delegation artifact drill-through audit after deploy. |

## Findings

### P1: Information Architecture

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P1.1 | Active | Sidebar exposes too many implementation nouns as peer destinations. | Real Safari nav review and DOM assertions. |
| P1.2 | Planned | `/ui/templates` and `/ui/gallery` duplicate the same gallery concept. | Canonical URL or explicit alias/redirect test. |
| P1.3 | Active | Terminology drifts between Capabilities, skills, Templates, gallery, protocols, tasks, and runs. | User-facing string inventory. |
| P1.4 | Partial | Approvals is removed from default nav, but contextual approval verification remains. | Contextual approval scenario. |
| P1.5 | Partial | Standalone delegations are real, and protocol-generated stage tasks now have run-context copy, but conversation drill-through still needs audit. | Safari route from conversation linked work to run/stage task. |
| P1.6 | Partial | Shared default visibility filtering is patched; Conversations and Protocols are Safari-verified. | Finish remaining default page checks in broad audit. |
| P1.7 | Done | Dashboard is operational, Team is fake, and Agents belongs with Build resources. | Nav grouping test plus real Safari pass after deploy. |

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
| P3.12 | Active | Artifact actions must be invariant everywhere. | Shared artifact row tests in runs, stages, tasks, conversations. |
| P3.13 | Active | Stale leases can read as ordinary `running`. | Stuck-lease row and overview assertions. |
| P3.14 | Partial | Default filtering is patched for Runs, Dashboard, Conversations, Agents, Protocols, Delegations, and Usage. | Real Safari default/audit toggle verification. |

### P4: Protocol Authoring, Protocol Catalog, Capabilities

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P4.6 | Partial | Workflow map must remain on-demand and interactive without replacing primary authoring. | Map interaction test. |
| P4.15 | Done | Create-stage flow blocked on assignment and could clobber draft data. | UI-only unassigned stage and draft-preservation tests. |
| P4.16 | Partial | Standard/operator authoring split must omit internals from standard DOM and API. | Negative tests for Advanced/custom runtime/internal fields. |
| P4.23 | Done | Blank stage required owner role. | Name-only stage creation test. |
| P4.24 | Done | Protocol list hides generated drafts by default and exposes compact generated families through a toggle. | Real Safari catalog verification passed on deployed `d2ac48a`. |
| P4.25 | Done | Capabilities must be a human catalog, not passive bot admin or internal selector list; generated/meta E2E capabilities are hidden by default. | Row click, internal-filter, selector consistency tests. |
| P4.26 | Done | Missing capability had no natural assignment path. | `New capability needed` UI-only scenario. |

### P5: Conversations, Agents, Collaboration

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P5.1 | Active | Conversation list filters and quick starts are busy, especially on mobile. | Filter-collapse/mobile smoke test. |
| P5.3 | Active | Conversation detail needs dedicated audit for composer, timeline, linked work, settings, focus, scroll, send/WS, markdown. | Dedicated conversation detail audit. |
| P5.10 | Partial | Conversation list filters generated/rehearsal records by default and keeps audit access explicit. | Human conversations prioritized in real Safari. |
| P5.11 | Partial | Agent list and Capabilities agent eligibility hide generated/rehearsal agents by default; detail still needs a work-first audit. | Agent work-first audit and tests. |
| P5.12 | Done | Conversations pagination is broken or unclear. | URL-addressable pagination, Playwright pass, and real Safari pass after deploy. |

### P6: Presentation, Accessibility, Responsive

| ID | Status | Finding | Verification |
|----|--------|---------|--------------|
| P6.1 | Planned | Breakpoints can create layout jumps. | Breakpoint review. |
| P6.3 | Planned | Protocol full rerender can cause keyboard/AT focus loss. | Keyboard focus preservation test. |
| P6.4 | Planned | Icon-only controls need ARIA verification. | Axe and manual keyboard pass. |
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

## Workstreams

### W1: Navigation And Product IA

Scope:

- Remove fake `Team`.
- Move `Agents` into Build unless redesigned as Operations-only.
- Move current Dashboard into Operations or split it into Home plus Operations
  Dashboard.
- Decide if default nav exposes `Delegations`.
- Keep deep links for `/ui/tasks` and `/ui/approvals`.

Acceptance:

- Default nav expresses Work, Build, Operations.
- No normal user has to infer whether Tasks or Runs is the right place for a
  protocol execution.
- No important direct delegation workflow is lost.

### W2: Capabilities And Agents

Scope:

- Finish pending Capabilities row click/detail/internal-filter patch.
- Hide internal/system capabilities from normal catalog.
- Keep bot management secondary.
- Make agent pages work-first, not operations-first.
- Group or hide Rehearsal/test agents from default normal views.

Acceptance:

- Capabilities opens to a usable catalog.
- Clicking Architecture or another capability opens meaningful details.
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

Acceptance:

- A user can explain a run state from row and Overview.
- A user can preview/download artifacts from every context where they appear.
- Protocol stage task evidence does not require choosing a separate peer app.

### W5: Protocol Authoring And Catalog

Scope:

- Keep completed unassigned-stage and missing-capability flows green.
- Preserve interactive workflow map on demand.
- Group/hide generated protocol variants.
- Keep Templates as a starter surface only if it does not duplicate Protocols.

Acceptance:

- Blank-to-published protocol authoring is possible through UI only.
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

## Immediate Execution Order

1. Commit, push, pull on octopus, redeploy, and hard-refresh real Safari.
2. Verify default generated/rehearsal/test filtering and audit toggles in real
   Safari across Conversations, Runs, Protocols, Agents, Capabilities, Dashboard,
   and Delegations.
3. Verify the lineage drill-through from Conversation -> linked work -> Run ->
   Stage task -> artifact actions.
4. Keep M3 excluded from current claims; do not block UI cleanup on M3 auth.
5. Run accessibility, keyboard, mobile, theme-contrast, and resilience checks.
6. Only then resume broad 500+ screenshot audit.

## Verification Matrix

| Command / Pass | What It Proves |
|----------------|----------------|
| `node --check` on edited JS | No syntax regressions in changed UI code. |
| `git diff --check` | No whitespace/patch hygiene issues. |
| `.venv/bin/python -m pytest tests/test_registry_ui_contract.py` | Static UI contracts match product terminology and shared primitives. |
| `./.tmp/playwright/node_modules/.bin/playwright test -c tests/e2e/playwright.config.js tests/e2e/playwright/protocol-ui.spec.js` | Protocol authoring, rehearsal, execution, conversations, and artifacts still work. |
| `./.tmp/playwright/node_modules/.bin/playwright test -c tests/e2e/playwright.config.js tests/e2e/playwright/registry-work-surface.spec.js` | Work/nav/runs/conversations/tasks/capabilities desktop behavior. |
| Real Safari nav pass | Deployed assets, cache, and actual browser behavior match tests. |
| Real Safari Capabilities pass | Human catalog is clickable and filters internals. |
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
| `/ui/templates` | `components/gallery.js` |
| `/ui/gallery` | `components/gallery.js` |
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
