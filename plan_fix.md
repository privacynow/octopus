**Strict Plan**

Current state is not acceptable.

- Desktop `Topology` is still a debug graph, not a usable inspection surface.
- Mobile `Topology` is broken enough that it should not be treated as a feature.
- `Overview` is improved, but still not proven to carry the full workflow story on its own.
- Internal naming, coverage audits, and test breadth are still unfinished debt.
- Static code alignment does not change any of that.

This plan assumes the visual evidence is the source of truth.

## 1. Non-Negotiable Product Decisions

1. `Overview` is the only default whole-workflow comprehension surface.
2. `Detail` is the only primary editor.
3. `Topology` is advanced inspection only.
4. Full-graph topology is not a mobile feature unless it becomes genuinely usable.
5. No duplicate overview surfaces.
6. No duplicate assignment pipelines.
7. No shipping with “internally still transitional” debt left in place if it directly affects future reasoning or tests.
8. Small-screen topology behavior must be controlled by one explicit, testable rule in product code and tests; no vague “mobile-ish” behavior.

## 2. Immediate Reality Check

Treat these as open defects, not polish:

- `Overview` still may not answer flow, gates, and endings strongly enough on its own.
- Desktop `Topology` is still visually poor.
- Mobile `Topology` is unusable.
- Internal `process` / `map` naming is stale conceptual debt.
- Assignment summary coverage is not exhaustively verified.
- Validation/publish issue surfacing is not exhaustively verified in UI.
- Tests do not yet lock the real product contract tightly enough.

Nothing in this list should be deferred as “later polish.”

## 3. Phase 0: Stop Lying To Ourselves

Before more implementation, lock these truths in [plan_fix.md](/Users/tinker/output/bots/telegram-agent-bot/plan_fix.md) and code comments where needed:

- Desktop topology is still bad.
- Mobile topology is not shippable in current form.
- Overview is still under acceptance review, not “done.”
- Static code review does not override live visual review.
- No further work should assume current topology is “good enough.”

This matters because completion theater is how debt survives.

## 4. Phase 1: Finish Overview Properly

This is the primary visual repair phase. Not a rename. Not a copy pass.

In [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js), [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js), and [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css):

- Strengthen the current overview so the workflow reads as one coherent narrative, not improved cards.
- Make mainline order dominant.
- Make review/branch points visible but visually secondary.
- Make endings contextual and local to the relevant section, not abstract summary residue.
- Make participant ownership readable without becoming the primary layout axis.
- Ensure the user can answer:
  - what happens first
  - where are the review gates
  - what can loop back
  - how can this workflow finish
- Do not rely on topology for any of those answers.

Acceptance gate:
- If a user still needs `Topology` to understand the Software Engineering template, `Overview` is not finished.

## 5. Phase 2: Remove Mobile Topology As Shipped Today

Do not keep the current mobile topology path alive while pretending it is merely rough.

In [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) and [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css):

- Define one explicit small-screen rule for topology behavior and use it consistently in code and tests.
- Default outcome for this phase: remove or suppress full-graph topology on small screens immediately.
- Remove topology connect/edit affordances on mobile entirely.
- Replace with one honest near-term state:
  - explicit message that full topology is desktop-only and Overview/Detail should be used on mobile
- Treat focused local topology on mobile as a later addition only if it clears the same usability bar as desktop focused topology.

Do not keep:
- cropped desktop graph
- scroll-box graph hunting
- tiny zoom controls
- dense graph actions in a narrow viewport

Acceptance gate:
- Mobile must not expose an unusable full graph.

## 6. Phase 3: Rebuild Topology As One Focus-First Design Unit

Do not treat topology scope and topology geometry as separate design problems. In the current code, projection and layout are too tightly coupled for that to be efficient or correct.

The current topology fails because it defaults to full-graph inspection.

In [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js):

- Replace full-graph-first topology data with focus-aware topology data designed together with the new layout rules.
- Support explicit scopes:
  - `focus`
  - `segment`
  - `full`
- Default to `focus`, not `full`.
- Scope should include:
  - selected step or segment
  - immediate predecessors
  - immediate successors
  - local branch targets
  - nearby outcomes

In [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js):

- Keep one topology renderer.
- Stop assuming topology is always a giant global graph.
- Make the default layout selection-centric and local.
- Design layout semantics together with the scope model:
  - primary spine
  - local branch attachments
  - contextual outcomes
  - selected path emphasis
  - de-emphasized distant context

Acceptance gate:
- Opening topology from a selected stage should show a readable local route picture first, not a wall of wiring.

Delivery slices for this phase:
- Slice A: define and ship focus/segment/full topology data model with the new layout contract.
- Slice B: ship desktop rendering against that contract and make `focus` the default opening state.

## 7. Phase 4: Replace The Desktop Topology Geometry

Do not waste time tweaking spacing on the current fixed-grid graph. That path is exhausted.

In [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js):

- Replace the current full-graph geometry assumptions:
  - fixed column/row dominance
  - top back-edge bands
  - far-right terminal rail
  - oversized empty canvas regions
- Compute topology layout from:
  - primary spine
  - local branch attachments
  - contextual outcomes
  - selected path emphasis
- Keep branch labels only where they add meaning.
- De-emphasize non-selected edges and distant context in focus mode.

Acceptance gate:
- Desktop topology must become readable as an inspection tool, not just “less misleading than before.”

## 8. Phase 5: Internal Naming Debt Must Be Removed

Do not leave `process` / `map` scattered through the code once the product model is stable.

In [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js), [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js), tests, and related strings:

- Rename internal view kinds from `process` to `overview`.
- Rename internal view kinds from `map` to `topology`.
- Update helpers, comments, state persistence keys, and test names.
- Handle persisted workflow-view state once:
  - migrate old stored values once, or
  - invalidate/reset old stored values once
- Do not keep dual-key or dual-value compatibility paths alive after the rename.
- Delete stale transitional terminology.
- Do this only after behavior is correct enough to avoid churn, but do not defer it indefinitely.

Acceptance gate:
- No active code path should still conceptually describe the product with obsolete surface names.

## 9. Phase 6: Exhaustive Assignment And Validation Audit

Do not assume the selector/assignment story is fully finished just because the runtime path improved.

In [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js), [documents.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py), [engine.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/engine.py), and related tests:

- Grep and audit every user-visible assignment summary.
- Ensure the same summary logic is used everywhere it should be:
  - overview rows
  - detail headers
  - step owner lines
  - participant editor
  - topology node sublabels where appropriate
- Audit every UI path that surfaces validation issues.
- Ensure `participant.selector_required` appears consistently where users need it.
- Decide and document the product meaning of `preferred_agent_id` for skill selectors.
- Remove any remaining ambiguity between authored assignment and runtime hinting.
- Produce a checked audit artifact in the repo or review notes that lists:
  - surface
  - assignment summary formatter/helper used
  - validation issue entry point
  - expected user-visible output/state

Acceptance gate:
- A user must never wonder how a stage resolves, and the answer must not vary by surface.

## 10. Phase 7: Delete Dead Paths, Don’t Just Ignore Them

Once the new Overview/Topology contract is in place:

- Remove any dead topology-mobile assumptions.
- Remove obsolete tests that validate the old full-graph-first behavior as default.
- Remove any stale CSS that only exists to support dead graph behaviors.
- Remove stale comments and stale plan text.
- Remove dead route/connect affordances that only made sense for the old topology-first assumptions.

No passive debt parking.

## 11. Phase 8: Tests Must Match The Real Product, Not The Intent

Update:
- [tests/e2e/playwright/protocol-ui.spec.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/protocol-ui.spec.js)
- [tests/e2e/playwright/protocol-ui-capture.spec.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/protocol-ui-capture.spec.js)
- [tests/test_registry_ui_contract.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_contract.py)
- [tests/test_registry_ui_kit_contract.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_kit_contract.py)
- [tests/test_protocols.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_protocols.py)
- [tests/test_protocol_engine.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_protocol_engine.py)

Add hard assertions for:
- overview is the default whole-workflow surface
- topology is explicit advanced inspection
- mobile does not expose unusable full topology
- the small-screen topology rule behaves deterministically at the chosen breakpoint
- topology defaults to focused inspection, not full graph
- assignment summaries are consistent across surfaces
- selector-required validation is surfaced consistently
- internal surface names and visible strings are aligned after cleanup

Use screenshots as hard review inputs, not vanity artifacts.

## 12. Hard Ship Blockers

Do not ship while any of these remain true:

- Software Engineering still requires topology for normal comprehension
- desktop topology is still dominated by edge soup and dead space
- mobile shows a cropped desktop graph
- topology opens full graph by default
- `process` / `map` naming debt is still active in the core surface model
- assignment summaries differ across surfaces
- validation issues are inconsistently surfaced
- dead topology-first code paths remain

## 13. Execution Order

1. Lock the harsh current-state assessment in the plan and comments.
2. Finish `Overview` to the actual acceptance bar.
3. Remove or suppress mobile full topology immediately.
4. Rebuild topology as focus-first.
5. Replace desktop topology geometry.
6. Audit and unify assignment/validation surfacing.
7. Rename internal surface model to `overview` / `topology`.
8. Delete dead paths.
9. Expand tests and visual review gates.
10. Only then call it complete.

## 14. Definition Of Done

This work is done only when:

- `Overview` fully carries the workflow story
- `Detail` remains the sole editor
- `Topology` is genuinely useful as advanced inspection on desktop
- mobile no longer exposes unusable topology
- internal naming matches the product model
- assignment and validation are consistent everywhere
- stale topology-first debt is deleted, not tolerated
