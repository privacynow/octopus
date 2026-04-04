---
name: code-review
display_name: Code Review
description: Reviews code for correctness, style, and security
---
When reviewing code, follow these guidelines:

- Read the full diff before commenting. Understand the intent of the change.
- Check for correctness first: logic errors, off-by-ones, null/undefined handling, race conditions.
- Flag security issues: injection, unvalidated input, credential exposure, missing auth checks.
- Evaluate error handling: are failures caught, logged, and surfaced appropriately?
- Assess readability: naming, function length, unnecessary complexity.
- Verify edge cases: empty inputs, boundary values, concurrent access.
- Suggest concrete fixes, not vague guidance. Show the corrected code when possible.
- Keep feedback proportional — distinguish blocking issues from style nits.
