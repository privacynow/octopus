"""Telegram channel package.

This package will own the complete Telegram channel implementation:

- `normalization.py` for inbound update normalization and admission
- `ingress.py` for PTB entrypoints and workflow translation
- `runtime_skills.py`, `conversation.py`, and `pending.py` for concern-local handlers
- `presenters.py` for Telegram-specific presentation helpers
- `egress.py` for outbound delivery
- `bootstrap.py` for app construction entrypoints
"""
