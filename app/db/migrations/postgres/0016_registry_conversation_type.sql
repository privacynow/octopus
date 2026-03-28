ALTER TABLE agent_registry.conversations
    ADD COLUMN IF NOT EXISTS conversation_type TEXT NOT NULL DEFAULT 'conversation';
