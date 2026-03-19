# Octopus CLI Implementation Status

## Baseline

- Track: `./octopus` unified CLI
- Plan: `PLAN-octopus-cli.md`
- Baseline branch: `feature/multi_registry`
- Baseline goal: replace the legacy startup scripts and env shim with a single `./octopus` entrypoint and `.deploy/`-based state model.

## Slice Log

- Complete: Slice 1 split the legacy env shim into focused libraries.
  Scope:
  - created `scripts/lib/bot.sh`, `scripts/lib/docker.sh`, `scripts/lib/provider.sh`, `scripts/lib/ui.sh`, `scripts/lib/state.sh`, and `scripts/lib/registry.sh`
  - moved all existing legacy env helper functions into the focused libraries
  - kept a temporary compatibility shim for the slice
  - rewired `start_instance.sh`, `stop_instance.sh`, `logs_instance.sh`, `provider_login.sh`, and `provider_status.sh` to source focused libraries directly
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/docker.sh scripts/lib/provider.sh scripts/lib/ui.sh scripts/lib/state.sh scripts/lib/registry.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - the low-level helpers still printed the expected missing-config guidance before the legacy shim was removed
  - provider status still surfaced the expected missing-config guidance before the legacy shim was removed
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
  - created a temporary `.deploy/bots/slice2-test/.env` and verified `start_instance.sh` / `stop_instance.sh` resolved the slug-based bot path
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
- Complete: Slice 6 first-bot `./octopus` flow.
  Scope:
  - added the root `./octopus` entrypoint and made it sourceable for shell-level contract tests
  - implemented the first-bot quick setup flow with Telegram identity validation, provider choice, provider auth bootstrap, env-file creation, doctor checks, token-repair loop, and background startup verification
  - persisted both Octopus-facing identity fields (`BOT_TELEGRAM_ID`, `BOT_TELEGRAM_USERNAME`, `BOT_DISPLAY_NAME`, `BOT_SLUG`) and current runtime-facing fields (`BOT_INSTANCE`, `BOT_AGENT_SLUG`, `BOT_AGENT_DISPLAY_NAME`)
  - added duplicate-bot detection keyed by `BOT_TELEGRAM_ID` so the same Telegram bot is not silently re-added as a second local deployment
  - added reusable state helpers for Telegram identity lookups ahead of the later management slices
  Tests:
  - `bash -n octopus scripts/lib/state.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_first_bot_flow.py tests/test_octopus_token_validation.py`
  - `.venv/bin/python -m pytest -q tests/contracts/test_transport_store_contract.py -k 'test_get_usage_since_filters_by_time and postgres' -n 0`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - ran a stubbed first-bot bootstrap simulation under Bash and verified the flow prints `This token belongs to <name> (@<username>).` with no naming prompt
  - verified the generated `.deploy/bots/example-bot/.env` contained the Telegram identity fields plus the current runtime fields needed by `app.config`
  - verified the success box references the new `./octopus` command surface
  Notes:
  - one unrelated postgres contract test was timing-sensitive on the first parallel full-suite pass; the isolated rerun passed immediately and the subsequent full-suite rerun was green
  Verified:
  - the first-run contract is now token-driven instead of asking the user to name the bot a second time
  - the first-bot flow preserves the token-repair and doctor-check behavior from the old guided path while moving state into `.deploy/bots/<slug>/.env`
  - Telegram identity is now the authoritative source for first-bot local identity, while the duplicate guard prevents accidental double deployment of the same Telegram bot
- Complete: Slice 7 multi-bot management.
  Scope:
  - implemented `./octopus status`, `./octopus start`, `./octopus stop`, `./octopus logs`, and `./octopus doctor`
  - added bot selection helpers with single-bot auto-selection and multi-bot interactive choice prompts
  - added the top-level state-aware main menu plus the first management submenu shell
  - switched status and management output to identity-aware labels using `BOT_DISPLAY_NAME` and `BOT_TELEGRAM_USERNAME`
  - kept “Add a bot” on the same token-driven bootstrap path as first-run so additional bots do not reintroduce a naming prompt
  - fixed a portability bug in env parsing where non-POSIX `\\s` handling in shell readers could corrupt values like `standalone`
  Tests:
  - `bash -n octopus scripts/lib/bot.sh scripts/app/start_instance.sh scripts/provider/build_bot_image.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified `cmd_status` prints the expected no-bots guidance when `.deploy/bots/` is empty
  - verified a single configured bot is auto-selected for `start`, `stop`, `logs`, and `doctor`
  - verified the manage menu header shows the human-facing bot identity instead of the raw slug
  Verified:
  - the public `./octopus` surface now supports day-2 bot operations instead of only first-run bootstrap
  - multi-bot selection works without regressing the single-bot “don’t ask unnecessary questions” rule
  - the shared env-reader fix closed a real bug in active scripts, not just in the new CLI path
- Complete: Slice 8 registry connect and switch flows.
  Scope:
  - implemented local and remote registry connection flows for standalone bots
  - implemented local→remote, remote→local, and disconnect flows for already-registered bots
  - upgraded “Add a bot” to support creating a new bot directly in registry mode while keeping Telegram identity as the only naming source
  - added `./octopus registry` local-registry status/start/stop/logs management
  - added state-based enrollment verification using the bot’s persisted `registry_state.json`, with doctor output and filtered logs only as fallback diagnostics
  - cleared persisted registry runtime state before registry target changes so stale `agent_id` / `agent_token` values are not reused against the wrong registry
  Tests:
  - `bash -n octopus scripts/lib/bot.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_registry_management.py tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py tests/test_octopus_registry_network.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified a standalone bot env can be rewritten into local-registry mode with the expected `BOT_AGENT_REGISTRY_URL` / `BOT_AGENT_REGISTRY_ENROLL_TOKEN` values
  - verified disconnect removes registry keys instead of leaving empty stubs behind
  - verified non-HTTPS remote registry URLs are rejected before any config change is written
  Verified:
  - registry attachment is now bot-scoped, not a global checkout switch
  - success messages stay context-aware and only print the localhost UI URL for local registry flows
  - registry switching now accounts for persisted runtime identity, preventing a subtle stale-token bug during re-enrollment
- Complete: Slice 9 full mode, guided edit, and advanced options.
  Scope:
  - implemented `./octopus --full` and full-mode setup paths for both first-bot and add-bot creation
  - extended bot env creation to persist full-mode settings such as role, tags, description, skills, allowed users, working directory, timeout, and completion webhook URL
  - made display name editable in the guided settings menu while keeping the Telegram-derived slug immutable
  - added guided edit flows for display name, role, tags, allowed users, timeout, and full-config editor handoff
  - split generic restart behavior from registry-target restarts so ordinary config edits do not wipe persisted registry identity
  - added the first advanced menu with full-setup entry and webhook-mode configuration
  Tests:
  - `bash -n octopus tests/test_octopus_full_mode.py`
  - `.venv/bin/python -m pytest -q tests/test_octopus_full_mode.py tests/test_octopus_registry_management.py tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified full-mode env generation writes both bot-local settings and registry settings when full setup chooses registry mode
  - verified display-name edits update both `BOT_DISPLAY_NAME` and `BOT_AGENT_DISPLAY_NAME`
  - verified clearing allowed users through the guided menu restores `BOT_ALLOW_OPEN=1` instead of preserving stale restrictions
  Verified:
  - full mode now extends the same Telegram-identity-first bootstrap path instead of reintroducing a naming prompt
  - guided edit behavior matches the product split: display name is editable, slug is not
  - advanced config paths no longer depend on raw env editing as the primary user experience
- Complete: Slice 10 removed the legacy startup surface and updated docs/tests.
  Scope:
  - deleted the legacy guided startup script, shared-runtime startup script, and temporary env shim
  - removed all remaining flat-env and old-script fallback logic from active shell helpers and provider scripts
  - tightened the low-level helper scripts to operate only on `.deploy/bots/<slug>/.env`
  - aligned the compose files, config loader, registry UI copy, and helper scripts with the `./octopus` + `.deploy/` contract
  - rewrote the README around `./octopus` as the only primary operator command
  - removed obsolete legacy-surface tests and updated the remaining docs/doctor/config tests to the new paths and wording
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/docker.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh scripts/provider/build_bot_image.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh scripts/provider/provider_logout.sh scripts/app/dev_up.sh scripts/db/dev_up_postgres.sh octopus`
  - `.venv/bin/python -m pytest -q tests/test_readme_operator.py tests/test_startup_diagnostics.py tests/test_config.py tests/test_doctor.py tests/test_octopus_registry_network.py tests/test_octopus_provider_auth.py tests/test_octopus_management.py tests/test_octopus_registry_management.py tests/test_octopus_full_mode.py tests/test_octopus_first_bot_flow.py`
  - `.venv/bin/python -m pytest -q tests/test_readme_commands.py tests/test_readme_operator.py tests/e2e/test_compose_flows_probe.py`
  - `.venv/bin/python -m pytest -q tests/contracts/test_transport_store_contract.py -k 'test_get_usage_since_filters_by_time and postgres' -n 0`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - repo-wide grep for the removed startup surface and flat env paths returned zero matches
  - verified the cleaned README still covers first-time setup, daily commands, and registry UI with `./octopus`
  - verified the provider and helper scripts no longer depend on hidden flat env files
  Verified:
  - the repo no longer ships or references the removed startup surface
  - the active shell/config/docs path is now coherent around `.deploy/` and `./octopus`
  - the cleanup did not leave stale breakage behind; the full suite passed after the regressions were fixed
