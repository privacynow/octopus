**Target State**

One coherent product:

- `Overview`: the single whole-workflow comprehension surface
- `Detail`: the only primary editing surface
- `Topology`: explicit advanced inspection

And one coherent assignment contract:

- `stage -> participant -> selector -> runtime resolution`

No parallel overview surfaces. No parallel assignment mechanisms. No legacy shims left active.

**Current Starting Point**

The current code already gives us the right raw materials:
- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) has `process | detail | map`, segment projection, participant-first editing, selector editor, and authoring-safe agent filtering.
- [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js) has one `workflowCanvas`, lifecycle header, and selector preview primitive.
- [documents.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py) is already the right boundary for canonicalization and validation.
- [engine.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/engine.py) is already close to selector-first dispatch, but still carries entry-agent preference/fallback semantics.
- [builtins.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/builtins.py) and [protocol_store.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/protocol_store.py) still need to fully align with the one-contract story.

**Phase 0: Freeze the Product Contract**

- Replace the current conceptual model `Process / Detail / Map` with end-state product language: `Overview / Detail / Topology`.
- Lock the rule that `Overview` is the only default whole-workflow comprehension surface.
- Lock the rule that `Topology` is advanced inspection only, not a second editor and not a second overview.
- Lock the rule that `participant.selector` is the one canonical authored assignment field.
- Lock the rule that `required_skills` is legacy input only.
- Lock the rule that incomplete assignment is explicit and publish-blocking.
- Update [plan_fix.md](/Users/tinker/output/bots/telegram-agent-bot/plan_fix.md) and any stale top-of-file comments so the repo no longer describes two overview surfaces or multiple assignment contracts.

**Phase 1: Finish Assignment Canonicalization**

- In [documents.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py), make canonicalization authoritative:
  - if `selector` exists, keep it
  - else if `required_skills` exists, synthesize `selector = { kind: "skill", value: first_skill }`
  - else leave selector empty and let validation fail
- Remove `required_skills` from the canonical in-memory/output document shape so round-tripping does not preserve two active fields.
- Define multi-skill legacy policy explicitly:
  - first skill becomes selector
  - additional skills trigger a validation/migration warning
  - no silent multi-skill runtime behavior remains
- Update [builtins.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/builtins.py) so all built-ins use explicit selectors only.
- Update any store/snapshot shaping in [protocol_store.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/protocol_store.py) so downstream persisted views derive skill summaries from selector, not legacy fields.

**Phase 2: Simplify Runtime to One Non-Rehearsal Contract**

- In [engine.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/engine.py), keep rehearsal override intact.
- Remove live non-rehearsal dependence on `required_skills`.
- Make non-rehearsal dispatch use canonical `participant.selector` only.
- Make `requested_skills` derive from selector only:
  - `skill` selector -> `[selector.value]`
  - otherwise `[]`
- Make `preferred_agent_id` behavior explicit:
  - either remove implicit entry-agent preference for normal skill routing
  - or keep it only as an explicit, documented runtime policy
- End state: no invisible entry-agent fallback as the normal publishable product path.

**Phase 3: Validation and Incomplete-State Enforcement**

- Extend protocol validation in [documents.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py) so these are first-class issues:
  - participant missing selector
  - invalid selector kind/value
  - multi-skill legacy warning/error
- Wire those issues into publish/activate gating so “cannot publish” is enforced by the same validation contract the UI shows.
- Ensure `Detail` and `Overview` both surface incomplete assignment clearly as `Unassigned` or equivalent.
- Remove any UI or runtime behavior that quietly makes incomplete assignment look valid.

**Phase 4: Consolidate Whole-Workflow Comprehension into One Overview**

- Evolve the current `process` surface in [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js) into the final `Overview`.
- This is not a rename-only phase. It is the primary visual-repair phase for whole-workflow comprehension.
- Do not add a second flow-first map. Absorb any useful “mainline continuity” ideas into `Overview` itself.
- `Overview` should answer:
  - what are the ordered sections?
  - what is the mainline flow?
  - where are review/branch points?
  - how can it end?
- Keep the unit of comprehension primarily segment/section-based, but enrich it enough that it feels like one coherent whole-workflow picture rather than a disconnected card list.
- `Overview` must be visually reworked so it reads as one workflow narrative:
  - clear ordered mainline
  - visible continuity between sections
  - review and branch points visible but visually secondary
  - endings shown near the sections or decisions that can reach them
  - enough connective structure that a user can answer “what is the flow?” without opening `Topology`
- The current process-card strip is not sufficient as the final answer unless it is upgraded to meet the comprehension bar above.
- Participant ownership stays annotation-level in `Overview`, not the main layout axis.
- Outcomes should be shown near relevant sections, not as a remote detached concept.
- `Overview` must not turn into a disguised mini-graph. The goal is flow comprehension, not another topology rendering.

**Phase 5: Keep Detail as the Only Editor**

- Leave `Detail` as the sole primary authoring surface in [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js).
- Reuse one shared assignment summary formatter across:
  - participant cards
  - stage owner lines
  - detail headers
  - overview summaries
  - topology node labels where useful
- Keep route editing in `Detail`.
- Ensure `Topology` adds no unique authoring requirement. At most it may keep expert shortcuts, but nothing ordinary depends on it.

**Phase 6: Demote Map to Explicit Topology**

- Reframe current `map` as `Topology` in [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js).
- Change labels and entry points so users understand this is an advanced all-routes view.
- Keep one graph engine in [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js); do not build a second graph renderer.
- Topology remains step-level and full-edge, but now it is honest about its job: inspection/debugging, not first understanding.
- Improve Topology only enough to be usable as an expert tool:
  - better fit/zoom defaults
  - clearer labeling for selected/branch routes
  - less dead space if easy to win
  - but do not spend effort trying to make it the primary narrative view
- Visual success for the product is judged first by `Overview`, not by whether `Topology` becomes beautiful.

**Phase 7: Remove Dead Paths and Naming Debt**

- Once `Overview / Detail / Topology` is live, remove old `process/map` naming where it only reflects outdated product semantics.
- Delete stale strings, tests, and comments that still imply:
  - two default overview surfaces
  - `Map` as a normal comprehension surface
  - `required_skills` as a normal authored field
  - invisible entry-agent fallback as ordinary behavior
- Audit [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js) and [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css) for dead branches tied to the old story.
- Keep one active pipeline per capability.

**Phase 8: Test the Product Contract**

- Update Python tests:
  - [tests/test_protocols.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_protocols.py)
  - [tests/test_protocol_engine.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_protocol_engine.py)
  - [tests/test_registry_ui_contract.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_contract.py)
  - [tests/test_registry_ui_kit_contract.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_kit_contract.py)
- Add assertions for:
  - canonical selector-first document shape
  - multi-skill legacy warning behavior
  - selector-derived `requested_skills`
  - no publish-ready participant without selector
  - overview/topology terminology and button labels
- Update Playwright flows:
  - whole workflow opens into `Overview`
  - `Detail` remains the only editor
  - `Topology` is explicit and advanced
  - assignment summaries are visible and understandable
- Treat screenshots as manual review support, not the only truth. Structural assertions should carry most of the contract.

**Phase 9: Rollout and Data Handling**

- Because backward compatibility is not a goal, do not add compatibility shims.
- Use one clean migration boundary in [documents.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py).
- For dev/staging data, choose explicitly:
  - migrate in place through canonicalization on load/save
  - or reset known test fixtures if that is cleaner
- Do not preserve two behaviors just to avoid touching old data.

**Acceptance Criteria**

- There is one default whole-workflow comprehension surface: `Overview`.
- There is one primary editor: `Detail`.
- There is one advanced all-routes inspection surface: `Topology`.
- `Overview` itself provides the visual repair of the default whole-workflow experience; it is not merely a renamed `Process`.
- A new user can answer “what is the flow, where are the review gates, and how can it end?” from `Overview` without needing `Topology`.
- A user can tell how any stage resolves from the UI without understanding internal selector mechanics.
- `participant.selector` is the only canonical authored assignment rule.
- `required_skills` is migration-only and no longer an active parallel contract.
- Incomplete assignment is explicit and blocks publish.
- Topology is discoverable for experts but no longer pretending to be the main explanation of the workflow.
- No duplicate overview UIs, no duplicate assignment pipelines, no legacy UI/runtime branches left active.

**Execution Order**

1. Freeze terminology and product contract.
2. Canonicalize documents and built-ins to selector-first.
3. Simplify engine/runtime payloads to selector-first.
4. Enforce validation/publish rules for incomplete assignment.
5. Add shared assignment summaries everywhere.
6. Upgrade `process` into the final `Overview` and complete the whole-workflow visual repair there.
7. Reframe `map` into explicit `Topology` and limit its work to expert usability.
8. Delete dead code, dead labels, and stale tests.
9. Run contract tests, browser tests, visual review, and deploy.
