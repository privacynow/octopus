-- Channel-neutral durable identity across runtime stores.
-- Version: 5

ALTER TABLE bot_runtime.work_items
    DROP CONSTRAINT IF EXISTS work_items_update_id_fkey;

ALTER TABLE bot_runtime.updates
    RENAME COLUMN update_id TO event_id;
ALTER TABLE bot_runtime.updates
    ALTER COLUMN event_id TYPE TEXT USING ('tg:' || event_id::text);
ALTER TABLE bot_runtime.updates
    RENAME COLUMN chat_id TO conversation_key;
ALTER TABLE bot_runtime.updates
    ALTER COLUMN conversation_key TYPE TEXT USING ('tg:' || conversation_key::text);
ALTER TABLE bot_runtime.updates
    RENAME COLUMN user_id TO actor_key;
ALTER TABLE bot_runtime.updates
    ALTER COLUMN actor_key TYPE TEXT USING ('tg:' || actor_key::text);

ALTER TABLE bot_runtime.work_items
    RENAME COLUMN update_id TO event_id;
ALTER TABLE bot_runtime.work_items
    ALTER COLUMN event_id TYPE TEXT USING ('tg:' || event_id::text);
ALTER TABLE bot_runtime.work_items
    RENAME COLUMN chat_id TO conversation_key;
ALTER TABLE bot_runtime.work_items
    ALTER COLUMN conversation_key TYPE TEXT USING ('tg:' || conversation_key::text);

ALTER TABLE bot_runtime.work_items
    ADD CONSTRAINT work_items_event_id_fkey
    FOREIGN KEY (event_id) REFERENCES bot_runtime.updates(event_id)
    ON DELETE CASCADE;

ALTER TABLE bot_runtime.sessions
    RENAME COLUMN chat_id TO conversation_key;
ALTER TABLE bot_runtime.sessions
    ALTER COLUMN conversation_key TYPE TEXT USING ('tg:' || conversation_key::text);

ALTER TABLE bot_runtime.usage_log
    RENAME COLUMN chat_id TO conversation_key;
ALTER TABLE bot_runtime.usage_log
    ALTER COLUMN conversation_key TYPE TEXT USING ('tg:' || conversation_key::text);

ALTER TABLE bot_runtime.user_access
    RENAME COLUMN user_id TO actor_key;
ALTER TABLE bot_runtime.user_access
    ALTER COLUMN actor_key TYPE TEXT USING ('tg:' || actor_key::text);
ALTER TABLE bot_runtime.user_access
    ALTER COLUMN granted_by TYPE TEXT USING (
        CASE
            WHEN granted_by = 0 THEN ''
            ELSE 'tg:' || granted_by::text
        END
    );
ALTER TABLE bot_runtime.user_access
    ALTER COLUMN granted_by SET DEFAULT '';

DROP INDEX IF EXISTS bot_runtime.idx_updates_chat;
CREATE INDEX IF NOT EXISTS idx_updates_conv
    ON bot_runtime.updates (conversation_key, received_at);

DROP INDEX IF EXISTS bot_runtime.idx_work_items_state;
CREATE INDEX IF NOT EXISTS idx_work_items_state
    ON bot_runtime.work_items (state, conversation_key);

DROP INDEX IF EXISTS bot_runtime.idx_work_items_chat;
CREATE INDEX IF NOT EXISTS idx_work_items_conv
    ON bot_runtime.work_items (conversation_key, state);

DROP INDEX IF EXISTS bot_runtime.idx_one_claimed_per_chat;
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_claimed_per_conv
    ON bot_runtime.work_items (conversation_key)
    WHERE state = 'claimed';

DROP INDEX IF EXISTS bot_runtime.idx_usage_log_chat;
CREATE INDEX IF NOT EXISTS idx_usage_log_conv
    ON bot_runtime.usage_log (conversation_key);
