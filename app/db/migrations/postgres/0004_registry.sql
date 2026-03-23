-- Registry schema (final target state).
-- Applied by postgres_migrate runner; version tracked in bot_runtime.schema_migrations.
-- Version: 4

CREATE SCHEMA IF NOT EXISTS agent_registry;

CREATE TABLE IF NOT EXISTS agent_registry.meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry.agents (
    agent_id                    TEXT PRIMARY KEY,
    agent_token                 TEXT NOT NULL UNIQUE,
    display_name                TEXT NOT NULL,
    slug                        TEXT NOT NULL UNIQUE,
    role                        TEXT NOT NULL DEFAULT '',
    registry_scope              TEXT NOT NULL DEFAULT 'full',
    skills_json                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags_json                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    description                 TEXT NOT NULL DEFAULT '',
    provider                    TEXT NOT NULL DEFAULT '',
    mode                        TEXT NOT NULL DEFAULT 'standalone',
    connectivity_state          TEXT NOT NULL DEFAULT 'standalone',
    current_capacity            INTEGER NOT NULL DEFAULT 0,
    max_capacity                INTEGER NOT NULL DEFAULT 1,
    channel_capabilities_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
    version                     TEXT NOT NULL DEFAULT '',
    bot_key                     TEXT NOT NULL DEFAULT '',
    runtime_health_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    last_heartbeat_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_agents_state
    ON agent_registry.agents (connectivity_state);
CREATE INDEX IF NOT EXISTS idx_registry_agents_name
    ON agent_registry.agents ((lower(display_name)));

CREATE TABLE IF NOT EXISTS agent_registry.agent_runtime_workers (
    agent_id                  TEXT NOT NULL,
    worker_id                 TEXT NOT NULL,
    process_role              TEXT NOT NULL DEFAULT '',
    started_at                TEXT NOT NULL DEFAULT '',
    last_seen_at              TEXT NOT NULL DEFAULT '',
    current_item_id           TEXT NOT NULL DEFAULT '',
    current_conversation_key  TEXT NOT NULL DEFAULT '',
    current_kind              TEXT NOT NULL DEFAULT '',
    items_processed           INTEGER NOT NULL DEFAULT 0,
    stale_recoveries_seen     INTEGER NOT NULL DEFAULT 0,
    last_error                TEXT NOT NULL DEFAULT '',
    mirrored_at               TEXT NOT NULL,
    PRIMARY KEY (agent_id, worker_id)
);
CREATE INDEX IF NOT EXISTS idx_registry_runtime_workers_seen
    ON agent_registry.agent_runtime_workers (agent_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.deliveries (
    seq             BIGSERIAL PRIMARY KEY,
    delivery_id     TEXT NOT NULL UNIQUE,
    target_agent_id TEXT NOT NULL,
    kind            TEXT NOT NULL,
    payload_json    JSONB NOT NULL,
    state           TEXT NOT NULL DEFAULT 'queued',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    leased_at       TEXT,
    acked_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_registry_deliveries_agent_state_seq
    ON agent_registry.deliveries (target_agent_id, state, seq);

CREATE TABLE IF NOT EXISTS agent_registry.conversations (
    conversation_id          TEXT PRIMARY KEY,
    target_agent_id          TEXT NOT NULL,
    title                    TEXT NOT NULL DEFAULT '',
    origin_channel           TEXT NOT NULL DEFAULT 'registry',
    external_conversation_ref TEXT NOT NULL DEFAULT '',
    status                   TEXT NOT NULL DEFAULT 'open',
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_conversations_updated
    ON agent_registry.conversations (updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external
    ON agent_registry.conversations(target_agent_id, origin_channel, external_conversation_ref);

CREATE TABLE IF NOT EXISTS agent_registry.routed_tasks (
    routed_task_id         TEXT PRIMARY KEY,
    parent_conversation_id TEXT NOT NULL,
    origin_agent_id        TEXT NOT NULL,
    target_agent_id        TEXT NOT NULL,
    title                  TEXT NOT NULL,
    request_json           JSONB NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'queued',
    summary                TEXT NOT NULL DEFAULT '',
    result_json            JSONB,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
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
    metadata_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (conversation_id) REFERENCES agent_registry.conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_events_conversation ON agent_registry.events(conversation_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_kind ON agent_registry.events(conversation_id, kind, seq);
CREATE INDEX IF NOT EXISTS idx_events_fts ON agent_registry.events
    USING GIN (to_tsvector('english', content));

CREATE TABLE IF NOT EXISTS agent_registry.skills_override (
    skill_name TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    set_by     TEXT NOT NULL DEFAULT 'ui',
    set_at     DOUBLE PRECISION NOT NULL
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
    requirements_json JSONB NOT NULL DEFAULT '[]',
    provider_config_json JSONB NOT NULL DEFAULT '{}',
    files_json JSONB NOT NULL DEFAULT '[]',
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]',
    provider_config_json JSONB NOT NULL DEFAULT '{}',
    files_json JSONB NOT NULL DEFAULT '[]',
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
