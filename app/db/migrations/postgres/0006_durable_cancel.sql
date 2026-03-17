-- Durable cancel metadata for active work items.
-- Version: 6

ALTER TABLE bot_runtime.work_items
    ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ;

ALTER TABLE bot_runtime.work_items
    ADD COLUMN IF NOT EXISTS cancel_requested_by TEXT NOT NULL DEFAULT '';

ALTER TABLE bot_runtime.work_items
    ADD COLUMN IF NOT EXISTS cancel_request_event_id TEXT NOT NULL DEFAULT '';
