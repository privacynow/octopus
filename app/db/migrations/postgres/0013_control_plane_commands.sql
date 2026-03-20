-- Phase 23 control-plane command bus.
-- Applied by postgres_migrate runner; version tracked in bot_runtime.schema_migrations.
-- Version: 13

CREATE TABLE IF NOT EXISTS bot_runtime.control_plane_commands (
    seq               BIGSERIAL PRIMARY KEY,
    command_id        TEXT NOT NULL UNIQUE,
    capability        TEXT NOT NULL,
    operation         TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'pending',
    priority          INTEGER NOT NULL DEFAULT 0,
    correlation_id    TEXT NOT NULL DEFAULT '',
    authority_ref     TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL DEFAULT '',
    result_json       TEXT,
    error             TEXT,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    max_retries       INTEGER NOT NULL DEFAULT 3,
    created_at        TIMESTAMPTZ NOT NULL,
    claimed_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    lease_expires_at  TIMESTAMPTZ,
    next_attempt_at   TIMESTAMPTZ,
    CONSTRAINT control_plane_commands_state_check
        CHECK (state IN ('pending', 'claimed', 'completed', 'failed', 'dead_letter')),
    CONSTRAINT control_plane_commands_authority_ref_nonempty
        CHECK (authority_ref <> '')
);

CREATE INDEX IF NOT EXISTS idx_cp_state
    ON bot_runtime.control_plane_commands (state, next_attempt_at, priority DESC, seq);

CREATE INDEX IF NOT EXISTS idx_cp_correlation
    ON bot_runtime.control_plane_commands (correlation_id)
    WHERE correlation_id <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_cp_idempotency
    ON bot_runtime.control_plane_commands (capability, operation, authority_ref, idempotency_key)
    WHERE idempotency_key <> '';
