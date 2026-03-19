-- Hash registry agent bearer tokens at rest while preserving one-time issuance.
-- Version: 11

CREATE EXTENSION IF NOT EXISTS pgcrypto;

UPDATE agent_registry.agents
SET agent_token = encode(digest(agent_token, 'sha256'), 'hex')
WHERE agent_token IS NOT NULL
  AND agent_token <> ''
  AND agent_token !~ '^[0-9a-f]{64}$';
