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
  - pending current slice commit
- Pending: S3 minimize subprocess environments.
- Pending: S4 tighten registry defaults and transport posture.
- Pending: S5 expand redaction and doctor/log sanitization.
- Pending: S6 add independent credential key management.
- Pending: S7 harden secret-bearing files and token storage.
- Pending: S8 add artifact extraction quotas.
- Pending: S9 restrict credential validation outbound targets.
