CREATE SCHEMA IF NOT EXISTS bot_credentials;

CREATE TABLE IF NOT EXISTS bot_credentials.credentials (
    actor_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    cred_key TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    PRIMARY KEY(actor_key, skill_name, cred_key)
);
