-- Add bot_key column to agents table for deterministic conversation IDs.
-- This column was added to 0004_registry.sql but existing databases that
-- already applied the original 0004 migration need this additive migration.

ALTER TABLE agent_registry.agents
    ADD COLUMN IF NOT EXISTS bot_key TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_bot_key
    ON agent_registry.agents (bot_key) WHERE bot_key != '';
