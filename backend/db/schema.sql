-- Desired state schema for Atlas declarative workflow.
-- Generate versioned migration files with:
--   make atlas-diff MIGRATION_NAME=<name>

CREATE TABLE memory_profiles (
  id BIGSERIAL PRIMARY KEY,
  workspace_type TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '1.0',
  profile_json JSONB NOT NULL,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_memory_profiles_scope UNIQUE (workspace_type, workspace_id)
);

CREATE INDEX idx_memory_profiles_scope ON memory_profiles (workspace_type, workspace_id);
