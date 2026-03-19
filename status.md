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
  - pending current slice commit
- Pending: S2 sanitize registry/client/user-visible error propagation.
- Pending: S3 minimize subprocess environments.
- Pending: S4 tighten registry defaults and transport posture.
- Pending: S5 expand redaction and doctor/log sanitization.
- Pending: S6 add independent credential key management.
- Pending: S7 harden secret-bearing files and token storage.
- Pending: S8 add artifact extraction quotas.
- Pending: S9 restrict credential validation outbound targets.
