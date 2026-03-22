-- Registry UI rebuild: events table, conversation identity columns, content tables
-- Corresponds to SQLite migrations v7 + v8

-- Truncate conversations (old rows incompatible with new schema)
DELETE FROM agent_registry.conversations;

-- Add identity columns for idempotent conversation creation
ALTER TABLE agent_registry.conversations
    ADD COLUMN IF NOT EXISTS external_conversation_ref TEXT NOT NULL DEFAULT '';

-- Note: origin_channel already exists from 0004_registry.sql; ensure it's present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'agent_registry' AND table_name = 'conversations'
        AND column_name = 'external_conversation_ref'
    ) THEN
        ALTER TABLE agent_registry.conversations ADD COLUMN external_conversation_ref TEXT NOT NULL DEFAULT '';
    END IF;
END $$;

-- Unique constraint for idempotent get-or-create
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external
    ON agent_registry.conversations(target_agent_id, origin_channel, external_conversation_ref);

-- Events table (replaces timeline_events for new event publishing)
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

-- Full-text search on event content
CREATE INDEX IF NOT EXISTS idx_events_fts ON agent_registry.events
    USING GIN (to_tsvector('english', content));

-- Runtime skills table
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
