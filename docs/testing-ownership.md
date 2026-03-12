# Test Suite Ownership Map

Which suite owns which runtime contract. One owner per contract;
`test_invariants.py` keeps only truly cross-cutting checks.

## Owner Suites

| Suite | Owns |
|-------|------|
| `test_execution_context.py` | Context hash consistency, stale detection, inspect sandbox integrity, ResolvedContext path parity, hash field sensitivity, session round-trips, execution config digest, extra_dirs forwarding, model profile resolution, project+model cross-invalidation |
| `test_request_flow.py` | Public trust enforcement, is_public_user/is_allowed predicates, command gating, rate-limit defaults, mixed trust ingress, execute_request trust threading, validate_pending, credential satisfaction, model command/callback parity, extra_dirs_from_denials, compact+public cross-feature, export resolved skills |
| `test_handlers.py` | Core handler routing, /help, /start, /session, /new, /doctor, /project |
| `test_handlers_approval.py` | Approval flow lifecycle, preflight→approve→execute, deny, timeout |
| `test_handlers_codex.py` | Codex-specific handler behavior, resume, thread management |
| `test_handlers_export.py` | /export handler, conversation history, document rendering |
| `test_handlers_output.py` | Reply formatting, message splitting, expand/collapse |
| `test_handlers_store.py` | /skills store commands, install, remove |
| `test_handlers_credentials.py` | Credential storage, satisfaction, clear |
| `test_handlers_admin.py` | Admin commands |
| `test_handlers_ratelimit.py` | Handler-level rate limiting behavior |
| `test_approvals.py` | Pure approval functions (build_preflight_prompt, format_denials) |
| `test_progress.py` | ProgressEvent→render contract, provider event mapping |
| `test_claude_provider.py` | Claude command construction, session state, resume |
| `test_codex_provider.py` | Codex command construction, event parsing |
| `test_transport.py` | Inbound type normalization, serialize/deserialize |
| `test_work_queue.py` | Durable queue primitives, work-item state transitions |
| `test_workitem_integration.py` | Worker/Telegram recovery boundaries, claim serialization, fresh command ownership (no false recovery notices), pre-claimed item handling, complete_work_item state guard |
| `test_storage.py` | SQLite session CRUD, path resolution, upload isolation |
| `test_sqlite_integration.py` | SQLite WAL mode, concurrent access |
| `test_config.py` | Config parsing, validation, env loading |
| `test_formatting.py` | trim_text, markdown conversion, split_html |
| `test_summarize.py` | Response summarization |
| `test_ratelimit.py` | Rate limiter primitives |
| `test_skills.py` | Skill resolution, digest computation, provider config |
| `test_store.py` | Skill store primitives, install, ref/object management |
| `test_store_e2e.py` | End-to-end skill store flows |
| `test_registry.py` | Registry fetch, digest verification |
| `tests/e2e/test_compose_flows.py` | Phase 12 Compose E2E: bootstrap, doctor, bot startup schema validation (run with `E2E_COMPOSE=1`) |

## Cross-Cutting (test_invariants.py)

Only tests that genuinely span multiple runtime boundaries stay here:

- Registry integrity (digest mismatch leaves no residue)
- Async boundary (registry I/O doesn't block event loop)
- Update-ID idempotency (messages, commands, callbacks)
- Chat lock busy/queued feedback
- Contention (approval, settings, clear-cred callbacks)
- Same-chat overlapping update completion

### Temporarily in test_invariants.py (pending future migration)

These tests have clear owners but haven't been moved yet:

- **Doctor warnings** → future `test_doctor.py` or `test_handlers.py`
- **Progress wording and heartbeat** → `test_progress.py`
- **Recovery and resume** → `test_workitem_integration.py` / provider suites
- **Error handlers** → `test_handlers.py`

## Deleted Overflow Files

These files were folded into owner suites and deleted (20 weak duplicates
removed, unique tests strengthened and moved):

- `test_high_risk.py` → `test_codex_provider.py`, `test_claude_provider.py`, `test_config.py`, `test_storage.py`, `test_request_flow.py`
- `test_edge_callbacks.py` → `test_handlers_approval.py` (2 unique kept, 2 dups deleted)
- `test_edge_sessions.py` → `test_handlers.py`, `test_handlers_approval.py` (4 unique kept, 3 dups deleted)
- `test_edge_providers.py` → `test_handlers.py` (1 unique kept, 6 dups deleted)
- `test_edge_formatting.py` → `test_formatting.py` (5 unique kept, 7 dups deleted)
