"""Shared infrastructure and cross-workflow ports.

Use `app.ports` only for boundaries that are shared across workflows or are
infrastructure-level concerns, for example:

- egress
- content store
- credential store
- registry store

Workflow-local requests, outcomes, and narrow workflow protocols belong in the
owning workflow package's `contracts.py`, not in `app.ports`.
"""
