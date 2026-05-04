-- ============================================================================
-- DeerFlow P0 + P1 Enterprise Features — PostgreSQL Migration
-- ============================================================================
-- Run: psql -h <host> -U <user> -d <database> -f 001_enterprise_schema.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- P0: Authentication — Tenants & Users
-- ============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL UNIQUE,          -- e.g. "acme-corp"
    name        TEXT NOT NULL,                 -- display name
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_tenant_id ON tenants (tenant_id);

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    username      TEXT NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',    -- bcrypt hash
    role          TEXT NOT NULL DEFAULT 'member',  -- admin | member
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, username)
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users (tenant_id);

-- Default admin user (password must be set via application)
INSERT INTO tenants (tenant_id, name) VALUES ('default', 'Default Tenant')
    ON CONFLICT (tenant_id) DO NOTHING;

-- ============================================================================
-- P0: Authentication — API Keys
-- ============================================================================

CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,                -- human-readable label
    key_hash     TEXT NOT NULL UNIQUE,         -- SHA-256 hash of the raw key
    key_prefix   TEXT NOT NULL,                -- first 16 chars for display (df-xxxxxxxx)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys (tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash);

-- ============================================================================
-- P0: Rate Limiting — Counter Storage (optional, for DB-backed mode)
-- ============================================================================

CREATE TABLE IF NOT EXISTS rate_limit_counters (
    id          BIGSERIAL PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,          -- rate limit key (e.g. "tenant:acme:/api/chat")
    counter     INTEGER NOT NULL DEFAULT 0,
    window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_expires ON rate_limit_counters (expires_at);

-- ============================================================================
-- P1: Content Safety — Audit Logs
-- ============================================================================

CREATE TABLE IF NOT EXISTS content_safety_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         TEXT NOT NULL,
    thread_id         TEXT,
    direction         TEXT NOT NULL CHECK (direction IN ('input', 'output')),
    role              TEXT NOT NULL,           -- user | assistant
    original_text     TEXT NOT NULL,
    sanitized_text    TEXT,                    -- after PII masking (null if unchanged)
    allowed           BOOLEAN NOT NULL,
    flagged_categories TEXT[] NOT NULL DEFAULT '{}',
    reasons           TEXT[] NOT NULL DEFAULT '{}',
    provider          TEXT,                    -- e.g. "regex_pii", "openai_moderation"
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_logs_tenant ON content_safety_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cs_logs_thread ON content_safety_logs (thread_id);

-- ============================================================================
-- P1: Cost Management — Token Usage Records
-- ============================================================================

CREATE TABLE IF NOT EXISTS token_usage (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    thread_id     TEXT,
    model_name    TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd      NUMERIC(12, 8) NOT NULL DEFAULT 0,
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_tenant_ts ON token_usage (tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_usage_tenant_date ON token_usage (tenant_id, (timestamp::DATE));
CREATE INDEX IF NOT EXISTS idx_usage_model ON token_usage (model_name);

-- ============================================================================
-- P1: Cost Management — Budget Configuration
-- ============================================================================

CREATE TABLE IF NOT EXISTS budgets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           TEXT NOT NULL UNIQUE,
    daily_limit_usd     NUMERIC(12, 4) NOT NULL DEFAULT 50.0,
    monthly_limit_usd   NUMERIC(12, 4) NOT NULL DEFAULT 1000.0,
    alert_threshold_pct NUMERIC(5, 4) NOT NULL DEFAULT 0.80,  -- 0.0–1.0
    action_on_exceed    TEXT NOT NULL DEFAULT 'block' CHECK (action_on_exceed IN ('block', 'warn')),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_budgets_tenant ON budgets (tenant_id);

-- Default budget for default tenant
INSERT INTO budgets (tenant_id) VALUES ('default')
    ON CONFLICT (tenant_id) DO NOTHING;

-- ============================================================================
-- P1: Cost Management — Model Pricing Reference
-- ============================================================================

CREATE TABLE IF NOT EXISTS model_pricing (
    id                  SERIAL PRIMARY KEY,
    model               TEXT NOT NULL UNIQUE,
    input_per_1k_tokens  NUMERIC(10, 6) NOT NULL DEFAULT 0,
    output_per_1k_tokens NUMERIC(10, 6) NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed common model pricing (examples — adjust as needed)
INSERT INTO model_pricing (model, input_per_1k_tokens, output_per_1k_tokens) VALUES
    ('gpt-4o',             0.00250, 0.01000),
    ('gpt-4o-mini',        0.00015, 0.00060),
    ('gpt-4-turbo',        0.01000, 0.03000),
    ('claude-sonnet-4-6',  0.00300, 0.01500),
    ('claude-opus-4-7',    0.01500, 0.07500),
    ('claude-haiku-4-5',   0.00080, 0.00400),
    ('deepseek-v4-pro',    0.00100, 0.00400)
    ON CONFLICT (model) DO NOTHING;

-- ============================================================================
-- Helper: materialized daily/monthly cost summary (optional, for fast dashboards)
-- ============================================================================

CREATE TABLE IF NOT EXISTS cost_summary_daily (
    tenant_id   TEXT NOT NULL,
    date        DATE NOT NULL,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    total_cost  NUMERIC(14, 8) NOT NULL DEFAULT 0,
    llm_calls   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, date)
);

-- ============================================================================
-- Helper function: refresh daily cost summary
-- ============================================================================

CREATE OR REPLACE FUNCTION refresh_cost_summary(target_date DATE DEFAULT CURRENT_DATE)
RETURNS void AS $$
BEGIN
    INSERT INTO cost_summary_daily (tenant_id, date, total_tokens, total_cost, llm_calls)
    SELECT
        tenant_id,
        timestamp::DATE,
        SUM(total_tokens),
        SUM(cost_usd),
        COUNT(*)
    FROM token_usage
    WHERE timestamp::DATE = target_date
    GROUP BY tenant_id, timestamp::DATE
    ON CONFLICT (tenant_id, date) DO UPDATE SET
        total_tokens = EXCLUDED.total_tokens,
        total_cost   = EXCLUDED.total_cost,
        llm_calls    = EXCLUDED.llm_calls;
END;
$$ LANGUAGE plpgsql;

COMMIT;
