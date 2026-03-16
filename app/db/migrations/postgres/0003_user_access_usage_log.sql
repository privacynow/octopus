-- Add user_access and usage_log tables for M10E access overrides
-- and M10B usage tracking.
-- Version: 3

CREATE TABLE IF NOT EXISTS bot_runtime.user_access (
    user_id    BIGINT PRIMARY KEY,
    access     TEXT NOT NULL CHECK (access IN ('allowed', 'blocked')),
    reason     TEXT NOT NULL DEFAULT '',
    granted_by BIGINT NOT NULL DEFAULT 0,
    granted_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_runtime.usage_log (
    id                BIGSERIAL PRIMARY KEY,
    chat_id           BIGINT NOT NULL,
    work_item_id      TEXT NOT NULL,
    provider          TEXT NOT NULL,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL NOT NULL DEFAULT 0.0,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_usage_log_chat
    ON bot_runtime.usage_log (chat_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_recorded_at
    ON bot_runtime.usage_log (recorded_at);
