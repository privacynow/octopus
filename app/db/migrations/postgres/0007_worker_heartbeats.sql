-- Durable worker heartbeat rows for Shared Runtime observability.
-- Version: 7

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
