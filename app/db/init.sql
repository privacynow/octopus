-- Current canonical Postgres schema for Octopus runtime, registry, content, and credentials.
-- This file is the only supported initialization path for application schemas.

CREATE SCHEMA IF NOT EXISTS bot_runtime;

CREATE TABLE IF NOT EXISTS bot_runtime.sessions (
    conversation_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    has_pending BOOLEAN NOT NULL DEFAULT FALSE,
    has_setup BOOLEAN NOT NULL DEFAULT FALSE,
    project_id TEXT,
    file_policy TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON bot_runtime.sessions (updated_at);

CREATE TABLE IF NOT EXISTS bot_runtime.updates (
    event_id TEXT PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    actor_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL DEFAULT 'received'
);
CREATE INDEX IF NOT EXISTS idx_updates_conv
    ON bot_runtime.updates (conversation_key, received_at);

CREATE TABLE IF NOT EXISTS bot_runtime.work_items (
    id TEXT PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE REFERENCES bot_runtime.updates(event_id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'queued',
    dispatch_mode TEXT NOT NULL DEFAULT 'fresh',
    worker_id TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    cancel_requested_at TIMESTAMPTZ,
    cancel_requested_by TEXT NOT NULL DEFAULT '',
    cancel_request_event_id TEXT NOT NULL DEFAULT '',
    CONSTRAINT chk_work_items_state CHECK (
        state IN ('queued', 'claimed', 'pending_recovery', 'done', 'failed')
    ),
    CONSTRAINT chk_work_items_claimed_worker CHECK (
        state != 'claimed' OR worker_id IS NOT NULL
    ),
    CONSTRAINT chk_work_items_claimed_at CHECK (
        state != 'claimed' OR claimed_at IS NOT NULL
    ),
    CONSTRAINT chk_work_items_dispatch_mode CHECK (
        dispatch_mode IN ('fresh', 'recovery')
    )
);
CREATE INDEX IF NOT EXISTS idx_work_items_state
    ON bot_runtime.work_items (state, conversation_key);
CREATE INDEX IF NOT EXISTS idx_work_items_conv
    ON bot_runtime.work_items (conversation_key, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_claimed_per_conv
    ON bot_runtime.work_items (conversation_key)
    WHERE state = 'claimed';

CREATE TABLE IF NOT EXISTS bot_runtime.user_access (
    actor_key TEXT PRIMARY KEY,
    access TEXT NOT NULL CHECK (access IN ('allowed', 'blocked')),
    reason TEXT NOT NULL DEFAULT '',
    granted_by TEXT NOT NULL DEFAULT '',
    granted_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_runtime.usage_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_key TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_usage_log_conv
    ON bot_runtime.usage_log (conversation_key);
CREATE INDEX IF NOT EXISTS idx_usage_log_recorded_at
    ON bot_runtime.usage_log (recorded_at);

CREATE TABLE IF NOT EXISTS bot_runtime.worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    process_role TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    current_item_id TEXT NOT NULL DEFAULT '',
    current_conversation_key TEXT NOT NULL DEFAULT '',
    current_kind TEXT NOT NULL DEFAULT '',
    items_processed BIGINT NOT NULL DEFAULT 0,
    stale_recoveries_seen BIGINT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_seen
    ON bot_runtime.worker_heartbeats (last_seen_at);

CREATE TABLE IF NOT EXISTS bot_runtime.control_plane_commands (
    seq BIGSERIAL PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE,
    admin_interface TEXT NOT NULL,
    admin_operation TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    correlation_id TEXT NOT NULL DEFAULT '',
    implementation_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL DEFAULT '',
    result_json TEXT,
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    CONSTRAINT control_plane_commands_state_check
        CHECK (state IN ('pending', 'claimed', 'completed', 'failed', 'dead_letter')),
    CONSTRAINT control_plane_commands_implementation_ref_nonempty
        CHECK (implementation_ref <> '')
);
ALTER TABLE bot_runtime.control_plane_commands
    ADD COLUMN IF NOT EXISTS admin_interface TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS admin_operation TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS implementation_ref TEXT NOT NULL DEFAULT '';
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'bot_runtime'
          AND table_name = 'control_plane_commands'
          AND column_name = 'capability'
    ) THEN
        UPDATE bot_runtime.control_plane_commands
        SET admin_interface = capability
        WHERE admin_interface = ''
          AND capability <> '';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'bot_runtime'
          AND table_name = 'control_plane_commands'
          AND column_name = 'operation'
    ) THEN
        UPDATE bot_runtime.control_plane_commands
        SET admin_operation = operation
        WHERE admin_operation = ''
          AND operation <> '';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'bot_runtime'
          AND table_name = 'control_plane_commands'
          AND column_name = 'authority_ref'
    ) THEN
        UPDATE bot_runtime.control_plane_commands
        SET implementation_ref = authority_ref
        WHERE implementation_ref = ''
          AND authority_ref <> '';
    END IF;
END $$;
ALTER TABLE bot_runtime.control_plane_commands
    DROP COLUMN IF EXISTS capability,
    DROP COLUMN IF EXISTS operation,
    DROP COLUMN IF EXISTS authority_ref;
CREATE INDEX IF NOT EXISTS idx_cp_state
    ON bot_runtime.control_plane_commands (state, next_attempt_at, priority DESC, seq);
CREATE INDEX IF NOT EXISTS idx_cp_correlation
    ON bot_runtime.control_plane_commands (correlation_id)
    WHERE correlation_id <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_cp_idempotency
    ON bot_runtime.control_plane_commands (admin_interface, admin_operation, implementation_ref, idempotency_key)
    WHERE idempotency_key <> '';

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

CREATE SCHEMA IF NOT EXISTS agent_registry;

CREATE TABLE IF NOT EXISTS agent_registry.meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry.agents (
    agent_id TEXT PRIMARY KEY,
    agent_token TEXT NOT NULL UNIQUE,
    bot_key TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT '',
    registry_scope TEXT NOT NULL DEFAULT 'full',
    skills_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'standalone',
    connectivity_state TEXT NOT NULL DEFAULT 'standalone',
    current_capacity INTEGER NOT NULL DEFAULT 0,
    max_capacity INTEGER NOT NULL DEFAULT 1,
    transport_implementations JSONB NOT NULL DEFAULT '[]'::jsonb,
    supported_admin_operations JSONB NOT NULL DEFAULT '[]'::jsonb,
    version TEXT NOT NULL DEFAULT '',
    runtime_health_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    trust_tier TEXT NOT NULL DEFAULT 'community',
    soft_deleted_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL
);
ALTER TABLE agent_registry.agents
    ADD COLUMN IF NOT EXISTS transport_implementations JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS supported_admin_operations JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS trust_tier TEXT NOT NULL DEFAULT 'community',
    ADD COLUMN IF NOT EXISTS soft_deleted_at TEXT NOT NULL DEFAULT '';
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'agent_registry'
          AND table_name = 'agents'
          AND column_name = 'transport_implementations_json'
    ) THEN
        UPDATE agent_registry.agents
        SET transport_implementations = transport_implementations_json
        WHERE transport_implementations = '[]'::jsonb
          AND transport_implementations_json <> '[]'::jsonb;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'agent_registry'
          AND table_name = 'agents'
          AND column_name = 'management_capabilities_json'
    ) THEN
        UPDATE agent_registry.agents
        SET supported_admin_operations = management_capabilities_json
        WHERE supported_admin_operations = '[]'::jsonb
          AND management_capabilities_json <> '[]'::jsonb;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_registry_agents_state
    ON agent_registry.agents (connectivity_state);
CREATE INDEX IF NOT EXISTS idx_registry_agents_name
    ON agent_registry.agents ((lower(display_name)));
CREATE INDEX IF NOT EXISTS idx_registry_agents_soft_deleted
    ON agent_registry.agents (soft_deleted_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_bot_key
    ON agent_registry.agents (bot_key)
    WHERE bot_key <> '';

CREATE TABLE IF NOT EXISTS agent_registry.agent_runtime_workers (
    agent_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    process_role TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT '',
    current_item_id TEXT NOT NULL DEFAULT '',
    current_conversation_key TEXT NOT NULL DEFAULT '',
    current_kind TEXT NOT NULL DEFAULT '',
    items_processed INTEGER NOT NULL DEFAULT 0,
    stale_recoveries_seen INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    mirrored_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, worker_id)
);
CREATE INDEX IF NOT EXISTS idx_registry_runtime_workers_seen
    ON agent_registry.agent_runtime_workers (agent_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.deliveries (
    seq BIGSERIAL PRIMARY KEY,
    delivery_id TEXT NOT NULL UNIQUE,
    target_agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    leased_at TEXT,
    acked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_registry_deliveries_agent_state_seq
    ON agent_registry.deliveries (target_agent_id, state, seq);

CREATE TABLE IF NOT EXISTS agent_registry.management_requests (
    request_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    delivery_id TEXT NOT NULL DEFAULT '',
    result_json JSONB,
    error_code TEXT NOT NULL DEFAULT '',
    error_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_registry_management_requests_agent_status
    ON agent_registry.management_requests (target_agent_id, status, created_at);

CREATE TABLE IF NOT EXISTS agent_registry.conversations (
    conversation_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'human',
    hidden_from_default_views BOOLEAN NOT NULL DEFAULT FALSE,
    title TEXT NOT NULL DEFAULT '',
    conversation_type TEXT NOT NULL DEFAULT 'conversation',
    origin_channel TEXT NOT NULL DEFAULT 'registry',
    external_conversation_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE agent_registry.conversations
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'human',
    ADD COLUMN IF NOT EXISTS hidden_from_default_views BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agent_registry.conversations
    ALTER COLUMN hidden_from_default_views SET DEFAULT FALSE;
UPDATE agent_registry.conversations
SET
    source_kind = CASE
        WHEN conversation_type = 'task_thread' OR external_conversation_ref LIKE 'routed-task:%' THEN 'delegation'
        WHEN external_conversation_ref LIKE 'protocol-run:%' THEN 'protocol_run'
        WHEN lower(title) LIKE '%rehearsal%' OR lower(external_conversation_ref) LIKE '%rehearsal%' THEN 'rehearsal'
        WHEN lower(title) LIKE '%test%' OR lower(external_conversation_ref) LIKE '%test%' THEN 'test'
        ELSE source_kind
    END,
    hidden_from_default_views = COALESCE(hidden_from_default_views, FALSE)
        OR lower(title) LIKE '%rehearsal%'
        OR lower(external_conversation_ref) LIKE '%rehearsal%'
        OR lower(title) LIKE '%test%'
        OR lower(external_conversation_ref) LIKE '%test%';
ALTER TABLE agent_registry.conversations
    ALTER COLUMN hidden_from_default_views SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_registry_conversations_updated
    ON agent_registry.conversations (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_conversations_default_updated
    ON agent_registry.conversations (hidden_from_default_views, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_conversations_type_default_updated
    ON agent_registry.conversations (conversation_type, hidden_from_default_views, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_conversations_agent_default_updated
    ON agent_registry.conversations (target_agent_id, hidden_from_default_views, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external
    ON agent_registry.conversations (target_agent_id, origin_channel, external_conversation_ref);

CREATE TABLE IF NOT EXISTS agent_registry.routed_tasks (
    routed_task_id TEXT PRIMARY KEY,
    parent_conversation_id TEXT NOT NULL,
    origin_agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'delegation',
    hidden_from_default_views BOOLEAN NOT NULL DEFAULT FALSE,
    title TEXT NOT NULL,
    request_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT NOT NULL DEFAULT '',
    result_json JSONB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE agent_registry.routed_tasks
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'delegation',
    ADD COLUMN IF NOT EXISTS hidden_from_default_views BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agent_registry.routed_tasks
    ALTER COLUMN hidden_from_default_views SET DEFAULT FALSE;
UPDATE agent_registry.routed_tasks
SET
    source_kind = CASE
        WHEN COALESCE(request_json #>> '{context,protocol_run_id}', '') <> '' THEN 'protocol_stage'
        WHEN lower(title) LIKE '%rehearsal%' THEN 'rehearsal'
        WHEN lower(title) LIKE '%test%' THEN 'test'
        ELSE source_kind
    END,
    hidden_from_default_views = COALESCE(hidden_from_default_views, FALSE)
        OR COALESCE(request_json #>> '{context,protocol_run_id}', '') <> ''
        OR lower(title) LIKE '%rehearsal%'
        OR lower(title) LIKE '%test%';
ALTER TABLE agent_registry.routed_tasks
    ALTER COLUMN hidden_from_default_views SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_registry_routed_tasks_updated
    ON agent_registry.routed_tasks (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_routed_tasks_default_updated
    ON agent_registry.routed_tasks (hidden_from_default_views, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_routed_tasks_status_default_updated
    ON agent_registry.routed_tasks (status, hidden_from_default_views, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_routed_tasks_parent_updated
    ON agent_registry.routed_tasks (parent_conversation_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_routed_tasks_protocol_run
    ON agent_registry.routed_tasks ((request_json #>> '{context,protocol_run_id}'), updated_at DESC)
    WHERE (request_json #>> '{context,protocol_run_id}') <> '';

CREATE TABLE IF NOT EXISTS agent_registry.events (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (conversation_id) REFERENCES agent_registry.conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_events_conversation
    ON agent_registry.events (conversation_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_kind
    ON agent_registry.events (conversation_id, kind, seq);
CREATE INDEX IF NOT EXISTS idx_events_fts
    ON agent_registry.events USING GIN (to_tsvector('english', content));

CREATE TABLE IF NOT EXISTS agent_registry.resources (
    resource_id TEXT PRIMARY KEY,
    owner_actor_ref TEXT NOT NULL DEFAULT '',
    source_surface TEXT NOT NULL DEFAULT 'registry',
    source_ref TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    storage_uri TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'active',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_registry_resources_owner
    ON agent_registry.resources (owner_actor_ref, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_resources_source
    ON agent_registry.resources (source_surface, source_ref, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_registry_resources_hash
    ON agent_registry.resources (content_hash, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.resource_attachments (
    attachment_id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'context',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    detached_at TEXT NOT NULL DEFAULT '',
    detached_by TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (resource_id) REFERENCES agent_registry.resources(resource_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_resource_attachment_live
    ON agent_registry.resource_attachments (resource_id, target_kind, target_ref, relation)
    WHERE detached_at = '';
CREATE INDEX IF NOT EXISTS idx_registry_resource_attachments_target
    ON agent_registry.resource_attachments (target_kind, target_ref, created_at DESC)
    WHERE detached_at = '';
CREATE INDEX IF NOT EXISTS idx_registry_resource_attachments_resource
    ON agent_registry.resource_attachments (resource_id, created_at DESC)
    WHERE detached_at = '';

CREATE TABLE IF NOT EXISTS agent_registry.protocol_definitions (
    protocol_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'draft',
    current_version_id TEXT NOT NULL DEFAULT '',
    owner_org_id TEXT NOT NULL DEFAULT 'local',
    visibility TEXT NOT NULL DEFAULT 'org_private',
    created_by TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    draft_definition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    draft_content_hash TEXT NOT NULL DEFAULT '',
    draft_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE agent_registry.protocol_definitions
    ADD COLUMN IF NOT EXISTS owner_org_id TEXT NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'org_private',
    ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS updated_by TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS draft_revision INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_protocol_definitions_lifecycle
    ON agent_registry.protocol_definitions (lifecycle_state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_definitions_owner
    ON agent_registry.protocol_definitions (owner_org_id, visibility, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_definitions_catalog_visible
    ON agent_registry.protocol_definitions (updated_at DESC, display_name ASC, slug ASC)
    WHERE visibility <> 'registry_template';
CREATE INDEX IF NOT EXISTS idx_protocol_definitions_template_catalog
    ON agent_registry.protocol_definitions (updated_at DESC, display_name ASC, slug ASC)
    WHERE visibility = 'registry_template';

CREATE TABLE IF NOT EXISTS agent_registry.protocol_definition_versions (
    protocol_definition_version_id TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    definition_json JSONB NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    published_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_definition_versions_protocol_version
    ON agent_registry.protocol_definition_versions (protocol_id, version);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_runs (
    protocol_run_id TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    protocol_definition_version_id TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'protocol_run',
    hidden_from_default_views BOOLEAN NOT NULL DEFAULT FALSE,
    entry_agent_id TEXT NOT NULL DEFAULT '',
    entry_authority_ref TEXT NOT NULL DEFAULT '',
    is_rehearsal BOOLEAN NOT NULL DEFAULT FALSE,
    root_conversation_id TEXT NOT NULL DEFAULT '',
    origin_channel TEXT NOT NULL DEFAULT '',
    workspace_ref TEXT NOT NULL DEFAULT '',
    repo_ref TEXT NOT NULL DEFAULT '',
    branch_ref TEXT NOT NULL DEFAULT '',
    problem_statement TEXT NOT NULL DEFAULT '',
    constraints_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    current_stage_execution_id TEXT NOT NULL DEFAULT '',
    current_stage_key TEXT NOT NULL DEFAULT '',
    termination_summary TEXT NOT NULL DEFAULT '',
    blocked_code TEXT NOT NULL DEFAULT '',
    blocked_detail TEXT NOT NULL DEFAULT '',
    run_org_id TEXT NOT NULL DEFAULT 'local',
    started_by TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    retention_until TEXT NOT NULL DEFAULT '',
    last_transition_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    parent_protocol_run_id TEXT NOT NULL DEFAULT '',
    parent_stage_execution_id TEXT NOT NULL DEFAULT '',
    fork_mode TEXT NOT NULL DEFAULT '',
    fork_reason TEXT NOT NULL DEFAULT ''
);
ALTER TABLE agent_registry.protocol_runs
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'protocol_run',
    ADD COLUMN IF NOT EXISTS hidden_from_default_views BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS blocked_code TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS blocked_detail TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS run_org_id TEXT NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS started_by TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS retention_until TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS last_transition_at TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS is_rehearsal BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS parent_protocol_run_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS parent_stage_execution_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS fork_mode TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS fork_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_registry.protocol_runs
    ALTER COLUMN hidden_from_default_views SET DEFAULT FALSE;
UPDATE agent_registry.protocol_runs
SET
    source_kind = CASE
        WHEN is_rehearsal THEN 'rehearsal'
        WHEN lower(problem_statement) LIKE '%test%' THEN 'test'
        ELSE source_kind
    END,
    hidden_from_default_views = COALESCE(hidden_from_default_views, FALSE)
        OR is_rehearsal
        OR lower(problem_statement) LIKE '%test%';
ALTER TABLE agent_registry.protocol_runs
    ALTER COLUMN hidden_from_default_views SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_protocol_runs_updated
    ON agent_registry.protocol_runs (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_status
    ON agent_registry.protocol_runs (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_org
    ON agent_registry.protocol_runs (run_org_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_rehearsal
    ON agent_registry.protocol_runs (is_rehearsal, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_default_updated
    ON agent_registry.protocol_runs (hidden_from_default_views, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_protocol_updated
    ON agent_registry.protocol_runs (protocol_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_entry_agent_updated
    ON agent_registry.protocol_runs (entry_agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_root_conversation_updated
    ON agent_registry.protocol_runs (root_conversation_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_origin_channel_updated
    ON agent_registry.protocol_runs (origin_channel, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_org_status_updated
    ON agent_registry.protocol_runs (run_org_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_runs_blocked_code_updated
    ON agent_registry.protocol_runs (blocked_code, updated_at DESC)
    WHERE blocked_code <> '';
CREATE INDEX IF NOT EXISTS idx_protocol_runs_parent
    ON agent_registry.protocol_runs (parent_protocol_run_id, updated_at DESC)
    WHERE parent_protocol_run_id <> '';

CREATE TABLE IF NOT EXISTS agent_registry.protocol_scenarios (
    protocol_scenario_id TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    stage_key TEXT NOT NULL DEFAULT '',
    participant_key TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    decision_summary TEXT NOT NULL DEFAULT '',
    response_text TEXT NOT NULL DEFAULT '',
    run_org_id TEXT NOT NULL DEFAULT 'local',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE agent_registry.protocol_scenarios
    ADD COLUMN IF NOT EXISTS decision TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS decision_summary TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_protocol_scenarios_protocol
    ON agent_registry.protocol_scenarios (protocol_id, stage_key);
CREATE INDEX IF NOT EXISTS idx_protocol_scenarios_org
    ON agent_registry.protocol_scenarios (run_org_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_run_participants (
    protocol_run_participant_id TEXT PRIMARY KEY,
    protocol_run_id TEXT NOT NULL,
    participant_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    required_skills_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_selector_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_agent_id TEXT NOT NULL DEFAULT '',
    resolved_authority_ref TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    resolution_outcome TEXT NOT NULL DEFAULT 'queued',
    resolution_reason TEXT NOT NULL DEFAULT '',
    selector_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_run_participants_unique
    ON agent_registry.protocol_run_participants (protocol_run_id, participant_key);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_stage_executions (
    protocol_stage_execution_id TEXT PRIMARY KEY,
    protocol_run_id TEXT NOT NULL,
    stage_key TEXT NOT NULL,
    participant_key TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    loop_iteration INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'queued',
    decision TEXT NOT NULL DEFAULT '',
    decision_summary TEXT NOT NULL DEFAULT '',
    input_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    routed_task_id TEXT NOT NULL DEFAULT '',
    failure_code TEXT NOT NULL DEFAULT '',
    failure_detail TEXT NOT NULL DEFAULT '',
    timeout_at TEXT NOT NULL DEFAULT '',
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_protocol_stage_executions_run
    ON agent_registry.protocol_stage_executions (protocol_run_id, started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_stage_executions_routed_task
    ON agent_registry.protocol_stage_executions (routed_task_id)
    WHERE routed_task_id <> '';

CREATE TABLE IF NOT EXISTS agent_registry.protocol_artifacts (
    protocol_artifact_id TEXT PRIMARY KEY,
    protocol_run_id TEXT NOT NULL,
    artifact_key TEXT NOT NULL,
    artifact_kind TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    workspace_path TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    exists BOOLEAN NOT NULL DEFAULT FALSE,
    modified_at TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL DEFAULT '',
    verification_state TEXT NOT NULL DEFAULT 'declared',
    produced_by_stage_execution_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    supersedes_protocol_artifact_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_protocol_artifacts_run
    ON agent_registry.protocol_artifacts (protocol_run_id, artifact_key, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_artifact_snapshots (
    artifact_snapshot_id TEXT PRIMARY KEY,
    protocol_artifact_id TEXT NOT NULL DEFAULT '',
    protocol_run_id TEXT NOT NULL,
    artifact_key TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL DEFAULT 'file',
    storage_uri TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    retention_state TEXT NOT NULL DEFAULT 'active',
    retention_until TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    deleted_at TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT '',
    produced_by_stage_execution_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_snapshots_run
    ON agent_registry.protocol_artifact_snapshots (protocol_run_id, artifact_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_snapshots_hash
    ON agent_registry.protocol_artifact_snapshots (content_hash, created_at DESC)
    WHERE retention_state <> 'deleted';
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_snapshots_stage
    ON agent_registry.protocol_artifact_snapshots (produced_by_stage_execution_id, artifact_key, created_at DESC)
    WHERE produced_by_stage_execution_id <> '' AND retention_state <> 'deleted';

CREATE TABLE IF NOT EXISTS agent_registry.workspace_cleanup_inventory (
    inventory_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT '',
    workspace_ref TEXT NOT NULL DEFAULT '',
    protocol_run_id TEXT NOT NULL DEFAULT '',
    scan_status TEXT NOT NULL DEFAULT 'completed',
    file_count BIGINT NOT NULL DEFAULT 0,
    total_bytes BIGINT NOT NULL DEFAULT 0,
    retained_bytes BIGINT NOT NULL DEFAULT 0,
    transient_bytes BIGINT NOT NULL DEFAULT 0,
    unknown_bytes BIGINT NOT NULL DEFAULT 0,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_cleanup_inventory_agent
    ON agent_registry.workspace_cleanup_inventory (agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workspace_cleanup_inventory_run
    ON agent_registry.workspace_cleanup_inventory (protocol_run_id, created_at DESC)
    WHERE protocol_run_id <> '';

CREATE TABLE IF NOT EXISTS agent_registry.protocol_artifact_runtime_instances (
    runtime_instance_id TEXT PRIMARY KEY,
    protocol_run_id TEXT NOT NULL,
    artifact_key TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'not_configured',
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    manifest_path TEXT NOT NULL DEFAULT '',
    artifact_path TEXT NOT NULL DEFAULT '',
    runtime_url TEXT NOT NULL DEFAULT '',
    ui_url TEXT NOT NULL DEFAULT '',
    api_url TEXT NOT NULL DEFAULT '',
    health_url TEXT NOT NULL DEFAULT '',
    internal_url TEXT NOT NULL DEFAULT '',
    pid INTEGER NOT NULL DEFAULT 0,
    port INTEGER NOT NULL DEFAULT 0,
    started_by TEXT NOT NULL DEFAULT '',
    stopped_by TEXT NOT NULL DEFAULT '',
    failure_code TEXT NOT NULL DEFAULT '',
    failure_detail TEXT NOT NULL DEFAULT '',
    log_tail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    stopped_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_runtime_run
    ON agent_registry.protocol_artifact_runtime_instances (protocol_run_id, artifact_key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_runtime_status
    ON agent_registry.protocol_artifact_runtime_instances (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_artifact_runtime_events (
    runtime_event_id TEXT PRIMARY KEY,
    runtime_instance_id TEXT NOT NULL,
    protocol_run_id TEXT NOT NULL,
    artifact_key TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    actor_ref TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_runtime_events_instance
    ON agent_registry.protocol_artifact_runtime_events (runtime_instance_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_artifact_runtime_events_run
    ON agent_registry.protocol_artifact_runtime_events (protocol_run_id, artifact_key, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_runtime_capability_tokens (
    capability_token_id TEXT PRIMARY KEY,
    capability_ref_hash TEXT NOT NULL UNIQUE,
    bearer_token_hash TEXT NOT NULL DEFAULT '',
    protocol_run_id TEXT NOT NULL,
    protocol_stage_execution_id TEXT NOT NULL,
    artifact_key TEXT NOT NULL DEFAULT '',
    participant_key TEXT NOT NULL DEFAULT '',
    target_agent_id TEXT NOT NULL DEFAULT '',
    allowed_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NOT NULL DEFAULT '',
    exchange_count INTEGER NOT NULL DEFAULT 0,
    max_exchange_count INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    actor_ref TEXT NOT NULL DEFAULT ''
);
ALTER TABLE agent_registry.protocol_runtime_capability_tokens
    DROP CONSTRAINT IF EXISTS protocol_runtime_capability_tokens_bearer_token_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_runtime_capability_tokens_bearer_hash
    ON agent_registry.protocol_runtime_capability_tokens (bearer_token_hash)
    WHERE bearer_token_hash <> '';
CREATE INDEX IF NOT EXISTS idx_protocol_runtime_capability_tokens_stage
    ON agent_registry.protocol_runtime_capability_tokens (protocol_stage_execution_id, revoked_at, expires_at);
CREATE INDEX IF NOT EXISTS idx_protocol_runtime_capability_tokens_run_artifact
    ON agent_registry.protocol_runtime_capability_tokens (protocol_run_id, artifact_key, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_transitions (
    protocol_transition_id TEXT PRIMARY KEY,
    protocol_run_id TEXT NOT NULL,
    from_stage_execution_id TEXT NOT NULL DEFAULT '',
    to_stage_execution_id TEXT NOT NULL DEFAULT '',
    transition_kind TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_type TEXT NOT NULL DEFAULT '',
    actor_ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_protocol_transitions_run
    ON agent_registry.protocol_transitions (protocol_run_id, created_at DESC);

ALTER TABLE agent_registry.protocol_definition_versions
    ADD COLUMN IF NOT EXISTS published_by TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_registry.protocol_run_participants
    ADD COLUMN IF NOT EXISTS resolution_outcome TEXT NOT NULL DEFAULT 'queued',
    ADD COLUMN IF NOT EXISTS resolution_reason TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS selector_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE agent_registry.protocol_stage_executions
    ADD COLUMN IF NOT EXISTS timeout_at TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS lease_owner TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS lease_expires_at TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_protocol_stage_executions_running_lease
    ON agent_registry.protocol_stage_executions (lease_expires_at)
    WHERE status = 'running' AND lease_expires_at <> '';
CREATE INDEX IF NOT EXISTS idx_protocol_stage_executions_running_timeout
    ON agent_registry.protocol_stage_executions (timeout_at)
    WHERE status = 'running' AND timeout_at <> '';
CREATE INDEX IF NOT EXISTS idx_protocol_stage_executions_failure_code
    ON agent_registry.protocol_stage_executions (failure_code)
    WHERE failure_code <> '';

ALTER TABLE agent_registry.protocol_artifacts
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS exists BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS modified_at TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS observed_at TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS verification_state TEXT NOT NULL DEFAULT 'declared';

ALTER TABLE agent_registry.protocol_artifact_snapshots
    ADD COLUMN IF NOT EXISTS produced_by_stage_execution_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_registry.protocol_transitions
    ADD COLUMN IF NOT EXISTS error_code TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS agent_registry.protocol_idempotency (
    protocol_idempotency_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL DEFAULT '',
    scope_ref TEXT NOT NULL DEFAULT '',
    action_name TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    request_hash TEXT NOT NULL DEFAULT '',
    response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_idempotency_unique
    ON agent_registry.protocol_idempotency (scope_kind, scope_ref, action_name, idempotency_key);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_auto_sessions (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',
    mode TEXT NOT NULL DEFAULT 'create',
    surface TEXT NOT NULL DEFAULT 'api',
    actor_ref TEXT NOT NULL DEFAULT '',
    chat_ref TEXT NOT NULL DEFAULT '',
    source_protocol_id TEXT NOT NULL DEFAULT '',
    source_version_id TEXT NOT NULL DEFAULT '',
    source_draft_revision INTEGER NOT NULL DEFAULT 0,
    target_protocol_id TEXT NOT NULL DEFAULT '',
    target_draft_revision INTEGER NOT NULL DEFAULT 0,
    requirement_text TEXT NOT NULL DEFAULT '',
    constraints_text TEXT NOT NULL DEFAULT '',
    resource_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_lessons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    planner_response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    draft_definition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    unresolved_decisions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    change_summary_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    applied_protocol_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE agent_registry.protocol_auto_sessions
    ADD COLUMN IF NOT EXISTS planner_response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS resource_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS run_lessons_json JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_protocol_auto_sessions_actor
    ON agent_registry.protocol_auto_sessions (actor_ref, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_protocol_auto_sessions_target
    ON agent_registry.protocol_auto_sessions (target_protocol_id, updated_at DESC)
    WHERE target_protocol_id <> '';
CREATE INDEX IF NOT EXISTS idx_protocol_auto_sessions_chat
    ON agent_registry.protocol_auto_sessions (chat_ref, updated_at DESC)
    WHERE chat_ref <> '';

CREATE TABLE IF NOT EXISTS agent_registry.protocol_auto_session_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_kind TEXT NOT NULL,
    actor_ref TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agent_registry.protocol_auto_sessions(session_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_auto_session_events_sequence
    ON agent_registry.protocol_auto_session_events (session_id, sequence);

CREATE TABLE IF NOT EXISTS agent_registry.protocol_compliance_events (
    protocol_compliance_event_id TEXT PRIMARY KEY,
    protocol_run_id TEXT NOT NULL DEFAULT '',
    protocol_definition_version_id TEXT NOT NULL DEFAULT '',
    event_kind TEXT NOT NULL DEFAULT '',
    actor_ref TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_protocol_compliance_events_run
    ON agent_registry.protocol_compliance_events (protocol_run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_registry.skills_override (
    skill_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    set_by TEXT NOT NULL DEFAULT 'ui',
    set_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_registry.runtime_skills (
    slug TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'custom',
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    is_mutable INTEGER NOT NULL DEFAULT 1,
    archived INTEGER NOT NULL DEFAULT 0,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    files_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    files_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    version_label TEXT NOT NULL DEFAULT '',
    changelog TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.skill_approvals (
    record_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.provider_guidance (
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'text',
    is_mutable INTEGER NOT NULL DEFAULT 1,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, scope_kind, scope_key)
);

CREATE TABLE IF NOT EXISTS agent_registry.guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'text',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry.guidance_approvals (
    record_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    revision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE SCHEMA IF NOT EXISTS bot_content;

CREATE TABLE IF NOT EXISTS bot_content.skill_namespaces (
    skill_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_content.skill_tracks (
    track_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES bot_content.skill_namespaces(skill_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'shared',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (skill_id, source_kind, source_uri, owner_actor)
);

CREATE TABLE IF NOT EXISTS bot_content.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES bot_content.skill_tracks(track_id) ON DELETE CASCADE,
    version_label TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL,
    skill_kind TEXT NOT NULL DEFAULT 'prompt',
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
);

CREATE TABLE IF NOT EXISTS bot_content.skill_files (
    revision_id TEXT NOT NULL REFERENCES bot_content.skill_revisions(revision_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    executable BOOLEAN NOT NULL DEFAULT FALSE,
    digest TEXT NOT NULL,
    PRIMARY KEY (revision_id, relative_path)
);

CREATE TABLE IF NOT EXISTS bot_content.provider_guidance_tracks (
    guidance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'system',
    scope_key TEXT NOT NULL DEFAULT '',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (provider, scope_kind, scope_key)
);

CREATE TABLE IF NOT EXISTS bot_content.provider_guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'markdown',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
);

CREATE TABLE IF NOT EXISTS bot_content.skill_approval_records (
    record_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES bot_content.skill_tracks(track_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES bot_content.skill_revisions(revision_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_content.provider_guidance_approval_records (
    record_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_revisions(revision_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_approval_records_track_id
    ON bot_content.skill_approval_records (track_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_guidance_approval_records_guidance_id
    ON bot_content.provider_guidance_approval_records (guidance_id, created_at DESC);

CREATE SCHEMA IF NOT EXISTS bot_credentials;

CREATE TABLE IF NOT EXISTS bot_credentials.credentials (
    actor_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    cred_key TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    PRIMARY KEY (actor_key, skill_name, cred_key)
);
