# Multi-Registry Connections & Channel Bootstrap Status

## Baseline

- Track: multi-registry connections and channel bootstrap
- Plan: `multiregistry_plan.md`
- Baseline branch: `feature/multi_registry`
- Baseline goal: replace singleton registry assumptions and hardwired channel dispatch with per-connection registry runtime state, dispatcher-owned channel routing, and optional Telegram.

## Slice Log

- Complete: Slice 1 contracts and stable bot identity.
  Scope:
  - added stable runtime `bot_identity.json` persistence in `app/agents/state.py`
  - exposed `bot_identity(data_dir)` and `load_bot_identity_state(data_dir)` without changing existing registry-state behavior
  - added `app/ports/channel.py` with `ChannelDescriptor`, `Channel`, `ChannelBootstrap`, and `ChannelIngress`
  - added `app/runtime/channel_dispatcher.py` with prefix registration, conflict detection, ref-based egress routing, active channel type discovery, descriptor lookup, and ingress lifecycle hooks
  - kept all existing runtime paths intact; no live dispatch or registry behavior changed in this slice
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py tests/test_channel_dispatcher.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified `bot_identity()` creates a stable 32-char runtime id, persists it under `agent/bot_identity.json`, and regenerates safely from corrupt state
  - verified dispatcher routing covers positive and negative cases: telegram ref, registry task ref, unknown ref rejection, and conflicting prefix rejection
  - verified dispatcher ingress lifecycle only builds/starts `ChannelBootstrap` ingresses, not plain `Channel` instances
  Review:
  - slice 1 stays within the existing state seam instead of introducing a parallel runtime state module
  - the new dispatcher is additive and unused by production call sites so there is no slice-1 behavior drift
  - full-suite validation required running outside the sandbox because the existing socket-bind test in `tests/test_octopus_registry_network.py` cannot bind under the sandbox; the elevated rerun passed cleanly
  Verified:
  - stable local bot identity now exists as runtime state, not env/config
  - the new channel contracts and dispatcher are in place for later slices
  - full suite status after slice 1: `1777 passed, 23 skipped`
- Complete: Slice 2 registry connection config and state.
  Scope:
  - added `RegistryConnectionConfig` and `RegistryConnectionState` to the shared agent type layer
  - extended `BotConfig` with `agent_registries` while keeping the old singleton fields projected from the first configured connection
  - taught `load_config()` to parse indexed `BOT_AGENT_REGISTRY_<n>_*` variables and to synthesize a default `agent_registries` entry from the existing singleton env vars
  - added per-connection state persistence under `data/agent/registries/<id>.json` without disturbing the old `registry_state.json` path
  - updated the shared test config factory to project singleton registry inputs into `agent_registries`
  - made `app.agents` lazy-load `AgentRuntime` / `start_agent_runtime_task` so shared agent types can be imported from `config.py` without a package-init cycle
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py tests/test_config.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified singleton registry env still projects into `cfg.agent_registries` as `registry_id="default"` while preserving the old `agent_registry_url` / `agent_registry_enroll_token` fields
  - verified indexed registry env parses into multiple connection configs in order and projects the first entry back to the old singleton fields
  - verified per-connection state round-trips to `agent/registries/<id>.json`, uses private file permissions, and falls back safely from corrupt JSON
  Review:
  - the new config/state path extends the existing config and state seams instead of introducing a second config loader or second state module
  - the lazy `app.agents` package surface fixed the only slice-2 integration regression at the package boundary instead of moving the new shared dataclasses out of the planned type layer
  - old runtime consumers are still green because the singleton config fields and `registry_state.json` path remain intact for scaffolding
  Verified:
  - per-connection registry config/state now exists without changing current runtime behavior
  - the slice-2 scaffolding for later runtime migration is in place and the repo remains fully green
  - full suite status after slice 2: `1781 passed, 23 skipped`
- Complete: Slice 3 Telegram channel bootstrap.
  Scope:
  - added `app/channels/telegram/channel.py` with `TelegramChannelBootstrap` and `TelegramChannelIngress`
  - kept `app/channels/telegram/bootstrap.py` as the existing PTB application-construction seam and wrapped it instead of duplicating handler-registration logic
  - switched `main.py` from direct `build_bootstrap()` / `run_polling()` / `run_webhook()` calls to dispatcher-managed Telegram ingress startup via `ChannelDispatcher`
  - kept the legacy single-registry runtime path in `post_init` unchanged for this slice; only Telegram lifecycle moved under the dispatcher
  - hardened `ChannelDispatcher.start_all_ingresses()` / `stop_all_ingresses()` so ingress startup failures surface immediately instead of hanging behind a background task
  - removed the now-dead `run_worker_process()` helper after the dispatcher cutover and kept `KeyboardInterrupt` handling aligned across worker, webhook, and polling modes
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_telegram_channel_state.py tests/test_shared_runtime.py tests/test_handlers.py tests/test_config.py tests/test_channel_dispatcher.py tests/test_zero_import_gates.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified dispatcher registration builds exactly one Telegram ingress and routes `telegram:` refs to `TelegramChannelEgress`
  - verified the new Telegram ingress follows PTB startup/shutdown order for polling and webhook paths and skips live updater startup for worker-only processes
  - verified `main.py` now builds Telegram ingress through `ChannelDispatcher` and no longer imports or calls `build_bootstrap()` directly
  - verified ingress startup failures now raise through the dispatcher instead of silently dying in an unmanaged task
  Review:
  - slice 3 reused the existing Telegram bootstrap file as the authoritative handler-registration owner instead of cloning PTB setup into a second module
  - the dispatcher cutover stayed scoped to Telegram; registry startup is still the old `start_agent_runtime_task()` path until slice 4 as planned
  - the only cleanup beyond the plan was removing dead startup code created by the cutover and tightening the dispatcher failure path to avoid a real operability regression
  Verified:
  - Telegram now satisfies the new `ChannelBootstrap` / `ChannelIngress` contract without introducing a parallel Telegram runtime path
  - `main.py` uses dispatcher-managed Telegram ingress startup while preserving current worker and registry scaffolding behavior
  - full suite status after slice 3: `1787 passed, 23 skipped`
- Complete: Slice 4 registry runtime.
  Scope:
  - added `app/agents/registry_runtime.py` with one wrapped `AgentRuntime` per configured registry connection and one sync loop per connection
  - extended `AgentRuntime` to accept an explicit `RegistryConnectionConfig`, per-connection state loading/saving, and an optional `kind_filter` for scoped polling
  - extended `AgentRegistryClient.poll()` with an optional `kind_filter` query so scoped registry polling can be threaded through the existing client seam
  - added runtime-only per-connection state loading in `app/agents/state.py`, including legacy projection from `registry_state.json` for the default connection and dual-write back to the legacy state file for the default connection during scaffolding
  - rewired `main.py` to construct `RegistryRuntime` and start/stop it from the Telegram dispatcher lifecycle instead of calling `start_agent_runtime_task()` directly
  - kept registry egress and ref routing unchanged for this slice; registry channels are still deferred to slice 5 and the old factory still owns registry refs during the scaffolding window
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_agents.py tests/test_agents_runtime.py tests/test_registry_runtime.py tests/test_config.py tests/test_telegram_channel_state.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified per-connection runtime polling annotates every delivered item with `registry_id` before it reaches the delivery handler
  - verified scoped polling uses `channel_input/channel_action` for channel connections and preserves legacy full-scope behavior without changing the old singleton runtime path
  - verified the default connection projects legacy `registry_state.json` into `registries/default.json` semantics on read and dual-writes back to the legacy file on save so old consumers stay green during scaffolding
  - verified `main.py` now starts and stops the registry runtime through Telegram lifecycle hooks instead of the old direct agent-runtime startup helper
  Review:
  - slice 4 extends the existing `AgentRuntime` path instead of forking a second registry runtime implementation, which keeps the battle-tested enrollment/heartbeat/poll loop authoritative
  - the only Telegram ingress change was making `bot_data` initialization resilient for both the real PTB application and the lightweight fake used by the channel-state tests
  - registry ref ownership and outbound routing were intentionally left on the old factory for this slice to avoid mixing the runtime cutover with the channel-registration cutover planned for slice 5
  Verified:
  - per-connection registry runtime ownership now exists without changing registry egress or ref-routing behavior ahead of schedule
  - `main.py` no longer relies on `start_agent_runtime_task()` for the live registry path
  - full suite status after slice 4: `1793 passed, 23 skipped`

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
- Complete: Slice 11 added final CLI contract coverage and reran the full suite.
  Scope:
  - added `tests/test_octopus_cli_contracts.py` for slug normalization, state queries, menu routing, compose-wrapper contracts, provider-auth marker behavior, and the repo-wide no-legacy-surface assertion
  - expanded README contract coverage so the shipped docs retain both the `./octopus` operator surface and the user-facing Telegram command list
  - fixed a real shell bug in `provider_is_authed()` where the old `! ...; $?` pattern masked provider failures and could leave `.authed` markers stale
  - cleaned `.gitignore` to drop old flat-env patterns and legacy comments so the repo-level zero-reference check is truthful
  Tests:
  - `bash -n octopus scripts/lib/state.sh scripts/lib/bot.sh scripts/lib/docker.sh scripts/lib/provider.sh scripts/lib/registry.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_cli_contracts.py tests/test_octopus_token_validation.py tests/test_octopus_provider_auth.py tests/test_octopus_registry_network.py tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py tests/test_readme_commands.py tests/test_readme_operator.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified the repo-wide banned-surface scan stays clean without excluding shipped source files
  - verified the compose-wrapper tests capture the actual argument ordering after the `.deploy/` cleanup
  - verified the authoritative provider-auth check now sets and clears `.authed` markers correctly
  Verified:
  - the final CLI contract now has direct tests for the remaining slice-11 acceptance gaps instead of relying on incidental coverage
  - the new tests found and drove out one real provider-auth bug before the final pass
  - final suite status: `1769 passed, 23 skipped`
- Follow-up: plan/example alignment after final rollout review.
  Scope:
  - updated the plan’s provider-auth path sections to match the slice-3 probe (`.claude`, `.claude.json`, `.codex`) instead of the earlier `.config/...` assumptions
  - documented the `BOT_DATA_DIR` fallback in Python config as a residual risk for host/debug runs, while noting the compose path sets `/home/bot/data` correctly
  - deleted the legacy root env artifacts and replaced the tracked reference template with `.deploy/bots/.env.example`
  - rewired `scripts/host/setup_instance.sh` to use the new tracked example path
  Tests:
  - `bash -n scripts/host/setup_instance.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_cli_contracts.py tests/test_octopus_provider_auth.py tests/test_readme_operator.py tests/test_readme_commands.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - the written plan now matches the probed implementation for provider auth
  - the repo no longer carries the legacy root env artifacts
  - full suite status after the follow-up remained `1769 passed, 23 skipped`
