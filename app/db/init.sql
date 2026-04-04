-- Current canonical Postgres schema for Octopus runtime, registry, content, and credentials.
-- This file is the only supported initialization path for application schemas.

CREATE SCHEMA IF NOT EXISTS bot_runtime;

CREATE TABLE IF NOT EXISTS bot_runtime.sessions (
    conversation_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    has_pending BOOLEAN NOT NULL DEFAULT FALSE,
    has_setup BOOLEAN NOT NULL DEFAULT FALSE,
    project_id TEXT,
    file_policy TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON bot_runtime.sessions (updated_at);

CREATE TABLE IF NOT EXISTS bot_runtime.updates (
    event_id TEXT PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    actor_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL DEFAULT 'received'
);
CREATE INDEX IF NOT EXISTS idx_updates_conv
    ON bot_runtime.updates (conversation_key, received_at);

CREATE TABLE IF NOT EXISTS bot_runtime.work_items (
    id TEXT PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE REFERENCES bot_runtime.updates(event_id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'queued',
    dispatch_mode TEXT NOT NULL DEFAULT 'fresh',
    worker_id TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    cancel_requested_at TIMESTAMPTZ,
    cancel_requested_by TEXT NOT NULL DEFAULT '',
    cancel_request_event_id TEXT NOT NULL DEFAULT '',
    CONSTRAINT chk_work_items_state CHECK (
        state IN ('queued', 'claimed', 'pending_recovery', 'done', 'failed')
    ),
    CONSTRAINT chk_work_items_claimed_worker CHECK (
        state != 'claimed' OR worker_id IS NOT NULL
    ),
    CONSTRAINT chk_work_items_claimed_at CHECK (
        state != 'claimed' OR claimed_at IS NOT NULL
    ),
    CONSTRAINT chk_work_items_dispatch_mode CHECK (
        dispatch_mode IN ('fresh', 'recovery')
    )
);
CREATE INDEX IF NOT EXISTS idx_work_items_state
    ON bot_runtime.work_items (state, conversation_key);
CREATE INDEX IF NOT EXISTS idx_work_items_conv
    ON bot_runtime.work_items (conversation_key, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_claimed_per_conv
    ON bot_runtime.work_items (conversation_key)
    WHERE state = 'claimed';

CREATE TABLE IF NOT EXISTS bot_runtime.user_access (
    actor_key TEXT PRIMARY KEY,
    access TEXT NOT NULL CHECK (access IN ('allowed', 'blocked')),
    reason TEXT NOT NULL DEFAULT '',
    granted_by TEXT NOT NULL DEFAULT '',
    granted_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_runtime.usage_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_usage_log_conv
    ON bot_runtime.usage_log (conversation_key);
CREATE INDEX IF NOT EXISTS idx_usage_log_recorded_at
    ON bot_runtime.usage_log (recorded_at);

CREATE TABLE IF NOT EXISTS bot_runtime.worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    process_role TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_item_id TEXT NOT NULL DEFAULT '',
    current_conversation_key TEXT NOT NULL DEFAULT '',
    current_kind TEXT NOT NULL DEFAULT '',
    items_processed BIGINT NOT NULL DEFAULT 0,
    stale_recoveries_seen BIGINT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_seen
    ON bot_runtime.worker_heartbeats (last_seen_at);

CREATE TABLE IF NOT EXISTS bot_runtime.control_plane_commands (
    seq BIGSERIAL PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE,
    capability TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    correlation_id TEXT NOT NULL DEFAULT '',
    authority_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL DEFAULT '',
    result_json TEXT,
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    CONSTRAINT control_plane_commands_state_check
        CHECK (state IN ('pending', 'claimed', 'completed', 'failed', 'dead_letter')),
    CONSTRAINT control_plane_commands_authority_ref_nonempty
        CHECK (authority_ref <> '')
);
CREATE INDEX IF NOT EXISTS idx_cp_state
    ON bot_runtime.control_plane_commands (state, next_attempt_at, priority DESC, seq);
CREATE INDEX IF NOT EXISTS idx_cp_correlation
    ON bot_runtime.control_plane_commands (correlation_id)
    WHERE correlation_id <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_cp_idempotency
    ON bot_runtime.control_plane_commands (capability, operation, authority_ref, idempotency_key)
    WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS bot_runtime.deferred_notifications (
    notification_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    actor_key TEXT NOT NULL,
    content TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deferred_notifications_target_actor
    ON bot_runtime.deferred_notifications (target_agent_id, actor_key, created_at);
CREATE INDEX IF NOT EXISTS idx_deferred_notifications_expires
    ON bot_runtime.deferred_notifications (expires_at);

CREATE SCHEMA IF NOT EXISTS agent_registry;

CREATE TABLE IF NOT EXISTS agent_registry.meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry.agents (
    agent_id TEXT PRIMARY KEY,
    agent_token TEXT NOT NULL UNIQUE,
    bot_key TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT '',
    registry_scope TEXT NOT NULL DEFAULT 'full',
    skills_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'standalone',
    connectivity_state TEXT NOT NULL DEFAULT 'standalone',
    current_capacity INTEGER NOT NULL DEFAULT 0,
    max_capacity INTEGER NOT NULL DEFAULT 1,
    channel_capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    management_capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    version TEXT NOT NULL DEFAULT '',
    runtime_health_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_agents_state
    ON agent_registry.agents (connectivity_state);
CREATE INDEX IF NOT EXISTS idx_registry_agents_name
    ON agent_registry.agents ((lower(display_name)));
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_bot_key
    ON agent_registry.agents (bot_key)
    WHERE bot_key <> '';

CREATE TABLE IF NOT EXISTS agent_registry.agent_runtime_workers (
    agent_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    process_role TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT '',
    current_item_id TEXT NOT NULL DEFAULT '',
    current_conversation_key TEXT NOT NULL DEFAULT '',
    current_kind TEXT NOT NULL DEFAULT '',
    items_processed INTEGER NOT NULL DEFAULT 0,
    stale_recoveries_seen INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    mirrored_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, worker_id)
);
CREATE INDEX IF NOT EXISTS idx_registry_runtime_workers_seen
    ON agent_registry.agent_runtime_workers (agent_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.deliveries (
    seq BIGSERIAL PRIMARY KEY,
    delivery_id TEXT NOT NULL UNIQUE,
    target_agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    leased_at TEXT,
    acked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_registry_deliveries_agent_state_seq
    ON agent_registry.deliveries (target_agent_id, state, seq);

CREATE TABLE IF NOT EXISTS agent_registry.management_requests (
    request_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    capability TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    delivery_id TEXT NOT NULL DEFAULT '',
    result_json JSONB,
    error_code TEXT NOT NULL DEFAULT '',
    error_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_registry_management_requests_agent_status
    ON agent_registry.management_requests (target_agent_id, status, created_at);

CREATE TABLE IF NOT EXISTS agent_registry.conversations (
    conversation_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    conversation_type TEXT NOT NULL DEFAULT 'conversation',
    origin_channel TEXT NOT NULL DEFAULT 'registry',
    external_conversation_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_conversations_updated
    ON agent_registry.conversations (updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external
    ON agent_registry.conversations (target_agent_id, origin_channel, external_conversation_ref);

CREATE TABLE IF NOT EXISTS agent_registry.routed_tasks (
    routed_task_id TEXT PRIMARY KEY,
    parent_conversation_id TEXT NOT NULL,
    origin_agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    request_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT NOT NULL DEFAULT '',
    result_json JSONB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_routed_tasks_updated
    ON agent_registry.routed_tasks (updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.events (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (conversation_id) REFERENCES agent_registry.conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_events_conversation
    ON agent_registry.events (conversation_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_kind
    ON agent_registry.events (conversation_id, kind, seq);
CREATE INDEX IF NOT EXISTS idx_events_fts
    ON agent_registry.events USING GIN (to_tsvector('english', content));

CREATE TABLE IF NOT EXISTS agent_registry.skills_override (
    skill_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    set_by TEXT NOT NULL DEFAULT 'ui',
    set_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry.runtime_skills (
    slug TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'custom',
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    is_mutable INTEGER NOT NULL DEFAULT 1,
    archived INTEGER NOT NULL DEFAULT 0,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    files_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    files_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    version_label TEXT NOT NULL DEFAULT '',
    changelog TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.skill_approvals (
    record_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.provider_guidance (
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'text',
    is_mutable INTEGER NOT NULL DEFAULT 1,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, scope_kind, scope_key)
);

CREATE TABLE IF NOT EXISTS agent_registry.guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'text',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.guidance_approvals (
    record_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    revision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE SCHEMA IF NOT EXISTS bot_content;

CREATE TABLE IF NOT EXISTS bot_content.skill_namespaces (
    skill_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_content.skill_tracks (
    track_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES bot_content.skill_namespaces(skill_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'shared',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (skill_id, source_kind, source_uri, owner_actor)
);

CREATE TABLE IF NOT EXISTS bot_content.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES bot_content.skill_tracks(track_id) ON DELETE CASCADE,
    version_label TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL,
    skill_kind TEXT NOT NULL DEFAULT 'prompt',
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
);

CREATE TABLE IF NOT EXISTS bot_content.skill_files (
    revision_id TEXT NOT NULL REFERENCES bot_content.skill_revisions(revision_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    executable BOOLEAN NOT NULL DEFAULT FALSE,
    digest TEXT NOT NULL,
    PRIMARY KEY (revision_id, relative_path)
);

CREATE TABLE IF NOT EXISTS bot_content.provider_guidance_tracks (
    guidance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'system',
    scope_key TEXT NOT NULL DEFAULT '',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (provider, scope_kind, scope_key)
);

CREATE TABLE IF NOT EXISTS bot_content.provider_guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'markdown',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
);

CREATE TABLE IF NOT EXISTS bot_content.skill_approval_records (
    record_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES bot_content.skill_tracks(track_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES bot_content.skill_revisions(revision_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_content.provider_guidance_approval_records (
    record_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_revisions(revision_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_approval_records_track_id
    ON bot_content.skill_approval_records (track_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_guidance_approval_records_guidance_id
    ON bot_content.provider_guidance_approval_records (guidance_id, created_at DESC);

CREATE SCHEMA IF NOT EXISTS bot_credentials;

CREATE TABLE IF NOT EXISTS bot_credentials.credentials (
    actor_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    cred_key TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    PRIMARY KEY (actor_key, skill_name, cred_key)
);
