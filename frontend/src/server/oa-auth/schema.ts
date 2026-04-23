import type { Sql } from "postgres";

let schemaPromise: Promise<void> | null = null;

export function ensureOaAuthSchema(sql: Sql): Promise<void> {
  schemaPromise ??= (async () => {
    await sql.unsafe(`
      CREATE TABLE IF NOT EXISTS oa_users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email varchar(255) NOT NULL UNIQUE,
        name varchar(100) NOT NULL DEFAULT '',
        display_name varchar(100) NOT NULL DEFAULT '',
        avatar varchar(500) NOT NULL DEFAULT '',
        department varchar(200) NOT NULL DEFAULT '',
        role varchar(20) NOT NULL DEFAULT 'user',
        openid varchar(255) UNIQUE,
        wx_user_id varchar(255) NOT NULL DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        last_login_at timestamptz
      );
    `);
    await sql.unsafe(`
      CREATE TABLE IF NOT EXISTS oa_sessions (
        id varchar(64) PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES oa_users(id) ON DELETE CASCADE,
        expires_at timestamptz NOT NULL,
        last_seen_at timestamptz,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
      );
    `);
    await sql.unsafe(`
      CREATE INDEX IF NOT EXISTS oa_sessions_user_id_idx ON oa_sessions (user_id);
    `);
  })();
  return schemaPromise;
}
