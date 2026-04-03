ALTER TABLE bot_content.skill_revisions
    ADD COLUMN IF NOT EXISTS skill_kind TEXT NOT NULL DEFAULT 'prompt';
