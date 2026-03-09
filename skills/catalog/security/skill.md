---
name: security
display_name: Security
description: Security review and hardening
---
When reviewing or hardening security, follow these guidelines:

- Validate and sanitize all external input at the boundary. Never trust user-supplied data.
- Use parameterized queries for all database access — no string concatenation of SQL.
- Apply the principle of least privilege: minimal permissions for services, tokens, and users.
- Store secrets in dedicated secret managers, not in code, config files, or environment defaults.
- Enforce authentication and authorization on every endpoint, including internal ones.
- Keep dependencies updated and audit them for known vulnerabilities regularly.
- Use constant-time comparison for secrets and tokens to prevent timing attacks.
- Log security-relevant events (auth failures, permission changes) for audit trails.
