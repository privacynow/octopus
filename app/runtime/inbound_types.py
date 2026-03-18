"""Shared normalized inbound and admission types.

This module is the intended home for inbound types that are consumed across
channels and runtime code, such as normalized inbound messages/actions and
admitted-envelope shapes.

Milestone 1 establishes the ownership boundary only. Existing implementations
remain in their current modules until the runtime migration milestones move them
here without compatibility aliases.
"""
