# Octopus CLI Implementation Status

## Baseline

- Track: `./octopus` unified CLI
- Plan: `PLAN-octopus-cli.md`
- Baseline branch: `feature/multi_registry`
- Baseline goal: replace `guided_start.sh`, `shared_start.sh`, and `lib_env.sh` with a single `./octopus` entrypoint and `.deploy/`-based state model.

## Slice Log

- Complete: Slice 1 split `lib_env.sh` into focused libraries.
  Scope:
  - created `scripts/lib/bot.sh`, `scripts/lib/docker.sh`, `scripts/lib/provider.sh`, `scripts/lib/ui.sh`, `scripts/lib/state.sh`, and `scripts/lib/registry.sh`
  - moved all existing `lib_env.sh` functions into the focused libraries
  - kept `lib_env.sh` as a temporary shim
  - rewired `start_instance.sh`, `stop_instance.sh`, `logs_instance.sh`, `provider_login.sh`, and `provider_status.sh` to source focused libraries directly
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/docker.sh scripts/lib/provider.sh scripts/lib/ui.sh scripts/lib/state.sh scripts/lib/registry.sh scripts/lib_env.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - `./scripts/app/start_instance.sh` with no env file prints the expected `.env.bot` creation guidance
  - `./scripts/app/stop_instance.sh` with no env file prints the expected `.env.bot` creation guidance
  - `./scripts/provider/provider_status.sh` with no env file prints the expected `.env.bot` creation guidance
  Verified:
  - the library split landed without changing current startup/provider behavior
  - the temporary shim preserves the existing operator-script test contract while callers move to the focused libraries
  - full suite remained green after the refactor
- Complete: Slice 2 introduce `.deploy/` state layout and slug-based wrappers.
  Scope:
  - add `scripts/lib/state.sh` queries and `.deploy/` directory helpers
  - add `normalize_slug()` to `scripts/lib/bot.sh`
  - rewrite `bot_compose()` around `.deploy/bots/<slug>/.env`
  - add `registry_compose()` and `provider_compose()`
  - update `start_instance.sh`, `stop_instance.sh`, and `logs_instance.sh` to prefer slug-based `.deploy` bots while keeping the old instance fallback for this slice only
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/state.sh scripts/lib/docker.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - created a temporary `.deploy/bots/slice2-test/.env` and verified `start_instance.sh` / `stop_instance.sh` resolved the slug-based bot path instead of asking for `.env.bot`
  - confirmed ordinary bot commands no longer require registry env interpolation just to parse the compose file
  Verified:
  - `.deploy/` is now the canonical state root for the new wrappers
  - slug-based low-level bot scripts work while the old instance fallback remains available for this transitional slice
  - the compose wrappers now inject temporary registry placeholders for non-registry bot/profile commands, avoiding unrelated compose parse failures
- Complete: Slice 3 shared provider auth volume.
  Scope:
  - populated `scripts/lib/provider.sh` with shared auth directory helpers, authoritative auth checks, and `.authed` hint updates
  - rewired provider login/status scripts to use `provider_compose()` and shared `.deploy/provider-auth/<provider>/` bind mounts
  - changed the bot and provider compose services to mount provider auth at `/home/bot/.provider-auth` and persist bot data only at `/home/bot/data`
  - updated `docker-entrypoint.sh` to create provider-auth symlinks before privilege drop and to chown only `/home/bot/data`
  - aligned provider logout cleanup with the auth paths actually used by the current images
  Probe:
  - built both provider images and verified live auth paths before finalizing the mount model
  - Claude currently writes auth/state under `/home/bot/.claude` and `/home/bot/.claude.json`
  - Codex currently writes auth/state under `/home/bot/.codex`
  - `.config/...` paths were not observed in this build, so they were not carried into the new shared-auth layout
  Tests:
  - `bash -n scripts/lib/provider.sh scripts/lib/docker.sh scripts/docker/docker-entrypoint.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh scripts/provider/provider_logout.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_provider_auth.py tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - rebuilt both provider images and verified the runtime entrypoint now exposes `/home/bot/.claude`, `/home/bot/.claude.json`, and `/home/bot/.codex` as symlinks into `/home/bot/.provider-auth`
  - verified two separate bot slugs can mount the same Claude auth directory without forcing a second login flow
  - confirmed host-side files under `.deploy/provider-auth/claude/` remained owned by the host user instead of being mutated by container startup
  Verified:
  - provider auth is now shared per provider, not per bot
  - the authoritative auth decision path is container-backed, while `.authed` remains only a cache for fast status UX
  - the new entrypoint behavior avoids chowning host-mounted auth state while preserving writable bot data under `/home/bot/data`
- Complete: Slice 4 shared Docker network with registry alias.
  Scope:
  - added an external `octopus-net` default network to the main compose file
  - introduced the local registry network alias `registry` so bot containers can use `http://registry:8787`
  - populated `scripts/lib/registry.sh` with port selection and local-registry bootstrap helpers
  - moved registry secrets and port state to `.deploy/registry/.env`
  - rewired `scripts/registry/start.sh` and `scripts/registry/stop.sh` around the new wrappers
  - cleaned up generated Docker names so the local registry now comes up as `octopus-registry-service-1` instead of `octopus-registry-registry-1`
  - renamed the shared provider helper project to `octopus-auth-<provider>` to avoid another duplicated generated container name
  Tests:
  - `bash -n scripts/lib/state.sh scripts/lib/registry.sh scripts/lib/docker.sh scripts/registry/start.sh scripts/registry/stop.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_registry_network.py tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - started the local registry via `./scripts/registry/start.sh` and verified a bot container could reach `http://registry:8787/healthz` over the shared network alias
  - verified the cleaned-up generated registry container name was `octopus-registry-service-1`
  - confirmed start/stop now remove renamed-service orphans instead of leaving stale registry containers behind
  Cleanup:
  - pruned unused Docker builder cache, dangling images, and stopped containers after the slice to keep local disk usage under control
  Verified:
  - the local registry network path is now real end-to-end, not just file-declared
  - the registry lifecycle uses `.deploy/registry/.env` as the only local registry config source
  - the singleton registry naming is cleaner and no longer repeats `registry` in generated container or volume names
- Complete: Slice 5 early Telegram token validation.
  Scope:
  - added `telegram_token_format_valid()` to `scripts/lib/bot.sh` for a fast format gate before any network work
  - added `validate_telegram_token()` to `scripts/lib/bot.sh` using a Python `urllib` helper fed by stdin instead of putting the token in command args
  - updated the helper contract to return the Telegram identity triple: `id`, `username`, and `first_name`
  Tests:
  - `bash -n scripts/lib/bot.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_token_validation.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified the helper can be faked in tests to return a valid identity triple without exposing the token in the child `python3` argv
  - verified rejected-token paths return nonzero and produce no helper output
  - verified a live `ps` scan during validation did not show the test token string in process args
  Verified:
  - Telegram token validation now happens with a dedicated helper that is safe to call before any Docker or provider work
  - the identity fields needed by later `./octopus` flows are now available from a single `getMe` call
  - the token-leak constraint is covered by both positive and negative tests, not just by code inspection
