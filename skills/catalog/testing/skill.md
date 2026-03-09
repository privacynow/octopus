---
name: testing
display_name: Testing
description: Write and fix tests, TDD guidance
---
When writing or fixing tests, follow these guidelines:

- Write tests that exercise real production behavior, not test harness proofs.
- Choose the highest-signal seam that still runs the real production path.
- Only substitute dependencies that are external, nondeterministic, slow, or expensive.
- Each test should have a clear name describing the scenario and expected outcome.
- Bug fixes always get a regression test that fails for the original defect.
- If code is hard to test honestly, simplify the production design rather than adding test scaffolding.
- Prefer deterministic assertions over flaky timing-dependent checks.
- Keep test setup minimal — if setup is large, the production API may need simplification.
