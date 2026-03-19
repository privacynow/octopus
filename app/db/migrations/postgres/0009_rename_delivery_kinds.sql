-- Rename legacy registry delivery kinds to the current channel-oriented values.
-- Version: 9

UPDATE agent_registry.deliveries
SET kind = 'channel_input'
WHERE kind = 'surface_input';

UPDATE agent_registry.deliveries
SET kind = 'channel_action'
WHERE kind = 'surface_action';
