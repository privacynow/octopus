"""Telegram channel package.

This package will own the complete Telegram channel implementation:

- inbound update normalization and admission
- ingress translation into workflow calls
- egress delivery
- Telegram-specific presentation
- PTB bootstrap/wiring

During Milestone 1 this package is structural only. Existing Telegram behavior
remains in legacy modules until later milestones move ownership here.
"""
