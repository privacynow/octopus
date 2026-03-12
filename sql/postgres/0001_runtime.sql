-- Phase 12 runtime schema. One namespace for bot runtime data.
-- Applied by db_bootstrap (full) or db_update (pending versions only).
-- Version: 1

CREATE SCHEMA IF NOT EXISTS bot_runtime;

CREATE TABLE IF NOT EXISTS bot_runtime.sessions (
    chat_id     BIGINT PRIMARY KEY,
    provider    TEXT NOT NULL DEFAULT '',
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    has_pending BOOLEAN NOT NULL DEFAULT FALSE,
    has_setup   BOOLEAN NOT NULL DEFAULT FALSE,
    project_id  TEXT,
    file_policy TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON bot_runtime.sessions (updated_at);

CREATE TABLE IF NOT EXISTS bot_runtime.updates (
    update_id   BIGINT PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    kind        TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL,
    state       TEXT NOT NULL DEFAULT 'received'
);
CREATE INDEX IF NOT EXISTS idx_updates_chat ON bot_runtime.updates (chat_id, received_at);

CREATE TABLE IF NOT EXISTS bot_runtime.work_items (
    id          TEXT PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    update_id   BIGINT NOT NULL UNIQUE REFERENCES bot_runtime.updates(update_id) ON DELETE CASCADE,
    state       TEXT NOT NULL DEFAULT 'queued',
    worker_id   TEXT,
    claimed_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_work_items_state CHECK (state IN ('queued','claimed','pending_recovery','done','failed')),
    CONSTRAINT chk_work_items_claimed_worker CHECK (state != 'claimed' OR worker_id IS NOT NULL),
    CONSTRAINT chk_work_items_claimed_at CHECK (state != 'claimed' OR claimed_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_work_items_state ON bot_runtime.work_items (state, chat_id);
CREATE INDEX IF NOT EXISTS idx_work_items_chat ON bot_runtime.work_items (chat_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_claimed_per_chat ON bot_runtime.work_items(chat_id) WHERE state = 'claimed';

CREATE TABLE IF NOT EXISTS bot_runtime.schema_migrations (
    version INT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
-- Migration runner records applied version after running this file.
