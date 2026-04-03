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
    UNIQUE(skill_id, source_kind, source_uri, owner_actor)
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
    PRIMARY KEY(revision_id, relative_path)
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
    UNIQUE(provider, scope_kind, scope_key)
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
    ON bot_content.skill_approval_records(track_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_guidance_approval_records_guidance_id
    ON bot_content.provider_guidance_approval_records(guidance_id, created_at DESC);
