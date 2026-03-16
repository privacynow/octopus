-- Phase 20 registry control-plane schema.
-- Applied by postgres_migrate runner; version tracked in bot_runtime.schema_migrations.
-- Version: 4

CREATE SCHEMA IF NOT EXISTS agent_registry;

CREATE TABLE IF NOT EXISTS agent_registry.meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry.agents (
    agent_id                  TEXT PRIMARY KEY,
    agent_token               TEXT NOT NULL UNIQUE,
    display_name              TEXT NOT NULL,
    slug                      TEXT NOT NULL UNIQUE,
    role                      TEXT NOT NULL DEFAULT '',
    skills_json               JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags_json                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    description               TEXT NOT NULL DEFAULT '',
    provider                  TEXT NOT NULL DEFAULT '',
    mode                      TEXT NOT NULL DEFAULT 'standalone',
    connectivity_state        TEXT NOT NULL DEFAULT 'standalone',
    current_capacity          INTEGER NOT NULL DEFAULT 0,
    max_capacity              INTEGER NOT NULL DEFAULT 1,
    surface_capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    version                   TEXT NOT NULL DEFAULT '',
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    last_heartbeat_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_agents_state
    ON agent_registry.agents (connectivity_state);
CREATE INDEX IF NOT EXISTS idx_registry_agents_name
    ON agent_registry.agents ((lower(display_name)));

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
    conversation_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    origin_surface  TEXT NOT NULL DEFAULT 'registry',
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_conversations_updated
    ON agent_registry.conversations (updated_at DESC);

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

CREATE TABLE IF NOT EXISTS agent_registry.timeline_events (
    seq             BIGSERIAL PRIMARY KEY,
    event_id        TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    routed_task_id  TEXT NOT NULL DEFAULT '',
    agent_id        TEXT NOT NULL DEFAULT '',
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT '',
    progress        INTEGER,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TEXT NOT NULL,
    body_tsv        tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(body, ''))
                    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_registry_timeline_conversation_seq
    ON agent_registry.timeline_events (conversation_id, seq);
CREATE INDEX IF NOT EXISTS idx_registry_timeline_fts
    ON agent_registry.timeline_events USING GIN (body_tsv);

CREATE TABLE IF NOT EXISTS agent_registry.skills_override (
    skill_name TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    set_by     TEXT NOT NULL DEFAULT 'ui',
    set_at     DOUBLE PRECISION NOT NULL
);
