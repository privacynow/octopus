# Security

Octopus is a local operator-controlled agent platform. Do not expose a Registry
or bot runtime to untrusted networks without an HTTPS reverse proxy, firewall or
VPN controls, strong UI credentials, and fresh per-host tokens.

## Sensitive State

Generated `.deploy/` contents are private operational state. They can contain
Registry tokens, Telegram bot tokens, provider login state, database volumes,
absolute host paths, workspace mounts, and historical bot identities. A public
clone should generate a new `.deploy/` directory instead of copying one from a
developer machine.

## Reporting

For this public review repository, do not file live credentials, tokens,
private prompts, run exports, or provider logs in public issues. Report security
concerns privately to the repository owner.

## Current Boundaries

- The browser UI uses session authentication and CSRF tokens for mutations.
- Agent APIs use enrollment tokens and issued agent tokens.
- Bot containers are powerful local execution environments, not locked-down
  multi-tenant sandboxes.
- The role model is suitable for a local/operator environment and is not a
  complete commercial multi-tenant authorization model.
