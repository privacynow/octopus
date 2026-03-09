---
name: refactoring
display_name: Refactoring
description: Code cleanup and modernization
---
When refactoring code, follow these guidelines:

- Ensure adequate test coverage exists before changing any behavior.
- Make one structural change at a time. Keep each commit focused and reviewable.
- Preserve external behavior exactly — refactoring means changing structure, not semantics.
- Extract when a function does more than one thing. Inline when indirection adds no clarity.
- Replace magic numbers and strings with named constants.
- Simplify conditional logic: flatten nested ifs, use early returns, eliminate dead branches.
- Prefer standard library constructs over hand-rolled equivalents.
- Verify all tests pass after each change before moving to the next.
