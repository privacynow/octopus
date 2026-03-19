# Security Remediation Plan

This file is the authoritative execution plan for the active security
hardening track. Reference-only planning artifacts outside this repo were
used as input, but execution is tracked here.

## Scope

The current tree has several security and operator-UX gaps:

1. Registry UI embeds the master UI token in browser JavaScript.
2. Registry defaults and transport posture are insecure by default.
3. Raw registry/backend details can reach Telegram users.
4. Provider and summarizer subprocesses inherit the full runtime
   environment.
5. Log redaction and doctor diagnostics do not comprehensively sanitize
   secrets.
6. Credential encryption depends on the Telegram bot token.
7. Secret-bearing env/state files are created without permission
   hardening and some startup flows print secrets.
8. Registry agent bearer tokens are stored plaintext at rest.
9. Registry artifact import lacks decompression-bomb protection.
10. Credential validation can call arbitrary URLs from skill metadata.
11. Remaining raw validation exceptions still reach Telegram users.

## Execution Rules

1. One logical slice per commit.
2. Update `status.md` at the end of every slice with:
   - slice name
   - changed contract
   - tests run
   - commit hash
3. Every slice must include:
   - positive tests
   - negative/gate tests
   - full test suite before the commit
4. Do not keep compatibility shims for insecure behavior.
5. Prefer the real ownership boundary:
   - browser UI auth in registry auth/http/ui
   - user-visible messaging in presenters
   - token/storage concerns in config/store/factory layers
   - subprocess env in one shared builder seam

## Slice Order

### Phase 1: Stop active leak paths

#### Slice S1
Remove the master `REGISTRY_UI_TOKEN` from browser HTML/JS.

- Add session-or-bearer auth for `/v1/ui/*`.
- Browser UI uses session cookies; CLI/API callers may still use bearer
  auth.
- Add CSRF protection for state-changing browser UI calls.
- Remove bearer-token injection from rendered HTML and UI JavaScript.
- Status: complete

#### Slice S2
Sanitize registry client/user-facing error propagation.

- Remove response bodies from `RegistryClientError`.
- Store user-facing error codes rather than raw backend text.
- Map degraded discovery failures to presenter-owned safe messages.
- Remove residual raw `ValueError` strings from Telegram runtime-skill
  authoring flows.

#### Slice S3
Minimize subprocess environments.

- Introduce a shared subprocess-env builder.
- Claude, Codex, and summarizer subprocesses get allowlisted env vars
  only.
- Preserve intentional skill credential pass-through without ambient
  env leakage.

### Phase 2: Harden infrastructure and storage

#### Slice S4
Tighten registry defaults and transport posture.

- Remove weak default registry tokens.
- Refuse insecure registry startup when required secrets are missing or
  known-default.
- Tighten UI/session behavior when HTTP is allowed only for explicit
  local-dev cases.

#### Slice S5
Expand redaction and doctor/log sanitization.

- Redact DSNs, bearer tokens, and configured secret values.
- Remove raw exception text from doctor diagnostics and unsafe log
  lines.

#### Slice S6
Decouple credential encryption from the Telegram token.

- Add `BOT_CREDENTIAL_KEY`.
- Keep Telegram-token fallback only for backwards compatibility, with a
  warning and recovery guidance.

#### Slice S7
Harden secret-bearing local files and token issuance/storage.

- Permission-harden generated env files and `registry_state.json`.
- Stop printing registry secrets to stdout.
- Hash registry agent tokens at rest while preserving one-time issuance
  on enroll.

#### Slice S8
Add archive extraction quotas.

- Cap expanded bytes, file count, and per-file size before extraction.

### Phase 3: Trust-boundary hardening

#### Slice S9
Restrict credential validation outbound targets.

- Add allowlist-driven validation-host policy.
- Log validation target host and skill name without logging the secret.
- Reject non-allowlisted validation URLs.

## Final Gates

- No rendered HTML or JS contains `REGISTRY_UI_TOKEN`.
- No app code uses `os.environ.copy()` for child processes.
- No Telegram user-facing path renders raw backend exception text.
- No registry startup path accepts implicit weak tokens.
- No operator-facing diagnostics print raw DB URLs, bearer tokens, or
  known secret values.
- Secret-bearing generated files are permission-hardened.
- Registry agent tokens are not stored plaintext server-side.
- Artifact extraction enforces expanded-size quotas.
- Full suite passes.
