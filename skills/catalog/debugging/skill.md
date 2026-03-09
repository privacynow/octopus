---
name: debugging
display_name: Debugging
description: Systematic bug investigation
---
When debugging issues, follow these guidelines:

- Reproduce the bug first. Get a reliable, minimal reproduction before theorizing.
- Read error messages and stack traces carefully — they usually point to the cause.
- Form a hypothesis, then design a test that would disprove it before making changes.
- Use binary search on the timeline: find the last known-good state via git bisect or log analysis.
- Check the obvious first: configuration, environment variables, dependency versions, permissions.
- Trace data flow end to end — verify inputs, transformations, and outputs at each step.
- Once fixed, write a regression test that fails for the original defect.
- Document the root cause, not just the fix, so the team learns from it.
