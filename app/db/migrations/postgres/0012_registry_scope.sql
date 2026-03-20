-- Phase 22 registry scope enforcement.
-- Applied by postgres_migrate runner; version tracked in bot_runtime.schema_migrations.
-- Version: 12

ALTER TABLE agent_registry.agents
    ADD COLUMN IF NOT EXISTS registry_scope TEXT NOT NULL DEFAULT 'full';

UPDATE agent_registry.agents
SET registry_scope = 'full'
WHERE coalesce(registry_scope, '') = '';
