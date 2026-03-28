-- Phase 12 deferred recipient notifications.
-- Version: 15

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
