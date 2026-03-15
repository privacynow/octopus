-- Add dispatch_mode to work_items for fresh vs recovery routing.
-- Version: 2

ALTER TABLE bot_runtime.work_items
    ADD COLUMN IF NOT EXISTS dispatch_mode TEXT NOT NULL DEFAULT 'fresh';

ALTER TABLE bot_runtime.work_items
    DROP CONSTRAINT IF EXISTS chk_work_items_dispatch_mode;

ALTER TABLE bot_runtime.work_items
    ADD CONSTRAINT chk_work_items_dispatch_mode
    CHECK (dispatch_mode IN ('fresh', 'recovery'));
