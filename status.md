# Security Remediation Status

## Baseline

- Track: security hardening
- Plan: `security_plan.md`
- Start state: browser UI carries master registry token, subprocesses
  inherit ambient env, registry defaults remain insecure, and several
  user/operator-facing paths still expose raw details.
- Baseline branch: `feature/skills`
- Baseline commit: `7545389`

## Slice Log

- Complete: S1 remove master UI token from browser and switch browser UI
  auth to session + CSRF.
  Tests:
  - `python3 -m py_compile app/channels/registry/auth.py app/channels/registry/http.py app/channels/registry/ui.py tests/test_registry_service.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_registry_service.py tests/test_registry_skills.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - rendered shell now carries a CSRF token instead of the master UI token
  - browser UI reads work with session cookies
  - browser UI writes require `X-CSRF-Token`
  - bearer auth still works for non-browser callers
  Commit:
  - `1d27a39`
- Complete: S2 sanitize registry/client/user-visible error propagation.
  Tests:
  - `python3 -m py_compile app/registry_errors.py app/agents/client.py app/agents/state.py app/agents/runtime.py app/agents/delegation.py app/runtime_health.py app/channels/telegram/presenters.py app/channels/telegram/ingress.py app/channels/telegram/runtime_skills.py app/workflows/runtime_skills/authoring.py tests/test_agents.py tests/test_handlers.py tests/test_handlers_delegation.py tests/test_doctor.py tests/test_telegram_presenters.py tests/test_lifecycle_workflows.py tests/test_handlers_store.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_agents.py tests/test_handlers.py tests/test_handlers_delegation.py tests/test_doctor.py tests/test_telegram_presenters.py tests/test_lifecycle_workflows.py tests/test_handlers_store.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - registry HTTP failures no longer embed response bodies in `RegistryClientError`
  - agent runtime state now stores stable registry error codes plus operator-only detail
  - Telegram discovery and degraded delegation flows render safe registry summaries instead of backend text
  - runtime-skill draft creation no longer falls back to raw `ValueError` strings
  Commit:
  - `14235e7`
- Complete: S3 minimize subprocess environments.
  Tests:
  - `python3 -m py_compile app/subprocess_env.py app/providers/claude.py app/providers/codex.py app/summarize.py tests/test_claude_provider.py tests/test_codex_provider.py tests/test_summarize.py tests/test_subprocess_env.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_claude_provider.py tests/test_codex_provider.py tests/test_summarize.py tests/test_subprocess_env.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - provider and summarizer subprocesses now use a shared allowlisted env builder instead of ambient `os.environ.copy()`
  - provider auth env and deliberate skill credential pass-through still reach subprocesses
  - runtime secrets like `BOT_TELEGRAM_TOKEN` no longer flow into provider/summarizer child environments by default
  - every Claude/Codex/summarizer subprocess launch passes an explicit env
  Commit:
  - `b3e774b`
- Complete: S4 tighten registry defaults and transport posture.
  Tests:
  - `python3 -m py_compile app/channels/registry/auth.py app/channels/registry/http.py app/config.py tests/test_registry_service.py tests/test_registry_skills.py tests/test_config.py tests/test_operator_scripts.py tests/e2e/test_compose_flows.py`
  - `bash -n scripts/lib_env.sh scripts/app/guided_start.sh scripts/app/shared_start.sh scripts/registry/start.sh`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_registry_service.py tests/test_registry_skills.py tests/test_config.py tests/test_operator_scripts.py tests/e2e/test_compose_flows.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - registry startup now rejects missing/default enrollment tokens and rejects known-default UI tokens
  - session cookies are secure by default and only allow HTTP when `REGISTRY_ALLOW_HTTP=1` is explicitly set
  - compose no longer ships default registry tokens and now binds the published registry port to localhost by default
  - guided/shared startup flows still support local HTTP registry URLs but now push remote registry URLs toward HTTPS
  Commit:
  - `8fa7ae6`
- Complete: S5 expand redaction and doctor/log sanitization.
  Tests:
  - `python3 -m py_compile app/startup_diagnostics.py app/runtime_health.py app/config.py app/webhook.py app/main.py tests/test_startup_diagnostics.py tests/test_runtime_health.py tests/test_config.py tests/test_webhook.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_startup_diagnostics.py tests/test_runtime_health.py tests/test_doctor.py tests/test_config.py tests/test_webhook.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - startup/log redaction now covers Telegram tokens, Postgres DSNs, bearer tokens, and configured secret values
  - traceback text emitted through log handlers is sanitized before it reaches operator-visible output
  - doctor/runtime health diagnostics no longer interpolate raw content-store or session-store exceptions into user/operator summaries
  - completion-webhook and startup URL logging now strip query secrets and embedded credentials
  Commit:
  - `65e536b`
- Complete: S6 add independent credential key management.
  Tests:
  - `python3 -m py_compile app/config.py app/credential_store.py app/credential_store_sqlite.py app/credential_store_postgres.py tests/support/config_support.py tests/test_credential_store_factory.py tests/test_config.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_credential_store_factory.py tests/contracts/test_credential_store_contract.py tests/test_config.py tests/test_handlers_credentials.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - `BOT_CREDENTIAL_KEY` now provides independent credential-encryption key management through `BotConfig` and the credential-store factory
  - Telegram-token fallback remains for backwards compatibility, but now emits an operator warning and explicit rotation guidance
  - credential-store backends log a clear recovery hint when stored credentials can no longer be decrypted with the current key material
  - repo operator docs and `.env.example` now describe the independent credential key and the bot-token-rotation impact
  Commit:
  - `b48baa9`
- Complete: S7 harden secret-bearing files and token storage.
  Tests:
  - `python3 -m py_compile app/registry_service/store_base.py app/registry_service/store.py app/registry_service/store_postgres.py app/agents/state.py tests/contracts/test_registry_store_contract.py tests/test_registry_service.py tests/test_agents.py tests/test_operator_scripts.py`
  - `bash -n scripts/lib_env.sh scripts/app/guided_start.sh scripts/app/shared_start.sh scripts/registry/start.sh`
  - `.venv/bin/python -m pytest -q -n 4 tests/contracts/test_registry_store_contract.py tests/test_registry_service.py tests/test_agents.py tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - registry agent bearer tokens are now hashed at rest in both SQLite and Postgres-backed stores while still being returned once at enrollment time
  - SQLite registry migrations upgrade legacy raw agent tokens in place and Postgres has a matching token-hash migration
  - generated bot env files, `.env.registry`, and `registry_state.json` are permission-hardened to private file modes
  - `scripts/registry/start.sh` no longer prints registry secrets to stdout and instead points operators to the private env file
  Commit:
  - `338c5b1`
- Complete: S8 add artifact extraction quotas.
  Tests:
  - `python3 -m py_compile app/registry.py tests/test_registry.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_registry.py tests/test_registry_service.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - registry artifact import now rejects oversized expanded payloads before extraction instead of only checking the compressed download size
  - registry artifact import now rejects artifacts with too many files or any single file above the per-file quota
  - existing registry import and digest verification flows still pass with the new pre-extraction quota checks in place
  Commit:
  - `0e8441d`
- Complete: S9 restrict credential validation outbound targets.
  Tests:
  - `python3 -m py_compile app/credential_validation.py app/credential_service.py app/workflows/runtime_skills/setup.py app/credential_flow.py tests/test_handlers_credentials.py tests/test_runtime_skill_use_cases.py`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_handlers_credentials.py tests/test_runtime_skill_use_cases.py tests/test_telegram_runtime_skills.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - outbound credential validation now rejects unapproved hosts before any network request is sent and uses an allowlist with operator-configurable host extensions
  - credential-validation logging now records the target host and owning skill name without logging the credential value or full validation URL
  - the setup prompt now shows the validation host to the user before they submit a credential, while built-in GitHub validation continues to work under the default host policy
  Commit:
  - pending current slice commit
