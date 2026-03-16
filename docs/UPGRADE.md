# Upgrade Guide

1. Run `git pull`.
2. Run `pip install -r requirements.txt`.
3. Restart the bot. SQLite migrations run automatically on startup.
4. Restart the registry service if it is running.
5. Check `journalctl -u telegram-agent-bot -n 50` for migration log lines.

Notes:
- Sessions and conversations are preserved across upgrades.
- Bot and registry schema versions are tracked automatically and migrate in place on startup.
- Restarting the registry service clears all active Registry UI login sessions.
- `REGISTRY_SESSION_SECRET` (optional): if set, Registry UI login sessions
  survive service restarts. If not set, a random key is generated each time
  the registry starts and all sessions are invalidated on restart. Set this
  in `.env.registry` to preserve sessions across upgrades or restarts.
  Generate a value with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
- Rollback is not automated. If you need to downgrade, restore from a backup taken before upgrading.
