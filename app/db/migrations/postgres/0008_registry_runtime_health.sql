-- Registry mirrored runtime-health summary and worker rows.
-- Version: 8

ALTER TABLE agent_registry.agents
    ADD COLUMN IF NOT EXISTS runtime_health_json JSONB NOT NULL DEFAULT '{}'::jsonb;

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
