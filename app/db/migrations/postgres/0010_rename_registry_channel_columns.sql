-- Rename remaining registry surface-named columns to channel vocabulary.
-- Version: 10

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'agent_registry'
          AND table_name = 'agents'
          AND column_name = 'surface_capabilities_json'
    ) THEN
        ALTER TABLE agent_registry.agents
        RENAME COLUMN surface_capabilities_json TO channel_capabilities_json;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'agent_registry'
          AND table_name = 'conversations'
          AND column_name = 'origin_surface'
    ) THEN
        ALTER TABLE agent_registry.conversations
        RENAME COLUMN origin_surface TO origin_channel;
    END IF;
END $$;
