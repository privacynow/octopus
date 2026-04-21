**Protocol UX And Rehearsal Fix Plan**

## Current Problem

The progressive stage stack is the right primary authoring surface now, but two
real issues remain:

1. The assignment editor still exposes too much selector-model complexity.
- `Required skill` and `Pinned agent` are both visible together all the time.
- The chips mix context and action too loosely.
- `Advanced` is still present without a clear end-user purpose.

2. Rehearsal is real, but the visual proof is still too shallow.
- We already prove that rehearsal runs are routed to the reserved rehearsal
  authority.
- We do not yet prove meaningful built-in template outcomes visually through the
  live harness.
- The current scenario model only prefills response text, which is too weak for
  Software Engineering and Document Approval outcome testing.

## Product Direction

### Assignment editor

The normal editor should be mode-driven again:

- `By skill`
  - primary input: `Required skill`
  - optional refinement: `Pin matching agent`
- `Specific agent`
  - primary input: `Agent`
  - optional refinement: `Limit to one of this agent's skills`
- `Custom runtime selector`
  - advanced disclosure only
  - not a peer to the primary modes

Rules:
- chips may remain clickable only when they are clearly quick-picks for the
  visible primary input
- informational chips must be visually non-interactive
- `Advanced` must stay secondary and explain exactly what it is for

### Rehearsal proof

Rehearsal must prove real workflow outcomes, not just panel visibility.

Target scenarios:
- Software Engineering:
  - planning
  - plan review revise
  - planning again
  - plan review accept
  - architecture review accept
  - implementation review revise
  - implementation again
  - implementation review accept
  - acceptance accept
- Document Approval:
  - draft
  - review revise
  - draft again
  - review accept
  - approve accept

## Implementation Sequence

1. Rework the assignment editor in place.
- no duplicate editor
- no parallel selector path
- primary mode choice
- advanced hidden behind disclosure

2. Extend rehearsal scenarios and responses so the live UI can drive real stage
   outcomes.
- scenarios carry decision metadata, not just response text
- rehearsal responses support the decision path cleanly
- write-capable rehearsal stages can satisfy output verification without
  requiring a separate fake execution system

3. Add visual, outcome-based rehearsal coverage for the built-in templates.
- Software Engineering review loop
- Document Approval revise/approve loop

4. Redeploy to `/Users/tinker/octopus` only.

5. Run the exhaustive live audit again.
- 500+ screenshots minimum
- authoring
- assignment by skill
- assignment by agent
- stage insertion
- stage deletion
- rehearsal progression
- published execution
- runs inspection

6. If the live audit finds defects, add them here immediately and continue until
   none remain.

## Done Means

This work is finished only when:

- the assignment editor feels like one clear authoring path instead of a
  selector-model projection
- `Advanced` is clearly secondary
- rehearsal visually proves meaningful outcomes on Software Engineering and
  Document Approval
- live Octopus authoring, rehearsal, execution, and runs flows all pass again
- the exhaustive audit completes with 500+ fresh screenshots
