-- Core memory persistence schema keyed by namespace_type/namespace_id.
-- Canonical storage is profile_json (file-like document semantics in Postgres).

CREATE TABLE IF NOT EXISTS memory_profiles (
  id BIGSERIAL PRIMARY KEY,
  namespace_type TEXT NOT NULL,
  namespace_id TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '1.0',
  profile_json JSONB NOT NULL,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT ck_memory_profiles_namespace_type CHECK (namespace_type IN ('org_user', 'global')),
  CONSTRAINT uq_memory_profiles_scope UNIQUE (namespace_type, namespace_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_profiles_scope ON memory_profiles (namespace_type, namespace_id);
