---
name: architecture
display_name: Architecture
description: System design and planning
---
When designing systems or evaluating architecture, follow these guidelines:

- Start from requirements and constraints, not from a technology wish list.
- Prefer simple designs with explicit data flow over clever abstractions.
- Draw clear module boundaries. Each component should have one owner and one reason to change.
- Favor composition over inheritance. Flat, composable pieces are easier to reason about.
- Design for failure: every network call can fail, every queue can back up, every disk can fill.
- Make decisions reversible where possible. Avoid lock-in without concrete payoff.
- Document key trade-offs and the reasoning behind them, not just the chosen path.
- Validate designs against real load and failure scenarios before committing to implementation.
