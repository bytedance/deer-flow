import { randomUUID } from "node:crypto";

import type { Sql } from "postgres";

import {
  getOaDevUserEmail,
  getOaAuthSessionExpiryMs,
  getOaSuperAdminEmail,
} from "./config";
import { devUserIdFromEmail } from "./dev-user-id";
import type { OAuthUserInfo } from "./oauth-provider";

export type UserRole = "user" | "admin" | "super_admin";

export type OaUserPublic = {
  id: string;
  email: string;
  name: string;
  displayName: string;
  avatar?: string;
  department?: string;
  role: UserRole;
  createdAt: string;
  lastLoginAt?: string;
  openid?: string;
  wxUserId?: string;
};

function rowToPublic(row: {
  id: string;
  email: string;
  name: string;
  display_name: string;
  avatar: string;
  department: string;
  role: string;
  openid: string | null;
  wx_user_id: string;
  created_at: Date;
  last_login_at: Date | null;
}): OaUserPublic {
  const role: UserRole =
    row.role === "admin" || row.role === "super_admin" ? row.role : "user";
  return {
    id: row.id,
    email: row.email,
    name: row.name,
    displayName: row.display_name,
    avatar: row.avatar || undefined,
    department: row.department || undefined,
    role,
    createdAt: row.created_at.toISOString(),
    lastLoginAt: row.last_login_at?.toISOString(),
    openid: row.openid ?? undefined,
    wxUserId: row.wx_user_id || undefined,
  };
}

export async function getUserById(
  sql: Sql,
  id: string,
): Promise<OaUserPublic | null> {
  const rows = await sql<
    {
      id: string;
      email: string;
      name: string;
      display_name: string;
      avatar: string;
      department: string;
      role: string;
      openid: string | null;
      wx_user_id: string;
      created_at: Date;
      last_login_at: Date | null;
    }[]
  >`
    SELECT id, email, name, display_name, avatar, department, role, openid, wx_user_id, created_at, last_login_at
    FROM oa_users WHERE id = ${id}::uuid
  `;
  const row = rows[0];
  return row ? rowToPublic(row) : null;
}

export async function getUserForActiveSession(
  sql: Sql,
  sessionId: string,
): Promise<OaUserPublic | null> {
  const rows = await sql<
    {
      id: string;
      email: string;
      name: string;
      display_name: string;
      avatar: string;
      department: string;
      role: string;
      openid: string | null;
      wx_user_id: string;
      created_at: Date;
      last_login_at: Date | null;
    }[]
  >`
    SELECT u.id, u.email, u.name, u.display_name, u.avatar, u.department, u.role, u.openid, u.wx_user_id, u.created_at, u.last_login_at
    FROM oa_sessions s
    JOIN oa_users u ON u.id = s.user_id
    WHERE s.id = ${sessionId}
      AND s.revoked_at IS NULL
      AND s.expires_at > now()
  `;
  const row = rows[0];
  if (!row) return null;
  await sql`
    UPDATE oa_sessions SET last_seen_at = now(), updated_at = now()
    WHERE id = ${sessionId}
  `;
  return rowToPublic(row);
}

export async function upsertUserFromOAuth(
  sql: Sql,
  info: OAuthUserInfo,
  openId: string,
): Promise<OaUserPublic> {
  const superEmail = getOaSuperAdminEmail();
  const isSuper =
    superEmail.length > 0 &&
    superEmail.toLowerCase() === info.email.toLowerCase();
  const dept = info.dept_str ?? info.dept ?? "";
  const wx = info.wx_user_id ?? "";

  const existing = await sql<{ id: string; role: string }[]>`
    SELECT id, role FROM oa_users WHERE email = ${info.email} LIMIT 1
  `;

  if (existing.length === 0) {
    const role: UserRole = isSuper ? "super_admin" : "user";
    const inserted = await sql<
      {
        id: string;
        email: string;
        name: string;
        display_name: string;
        avatar: string;
        department: string;
        role: string;
        openid: string | null;
        wx_user_id: string;
        created_at: Date;
        last_login_at: Date | null;
      }[]
    >`
      INSERT INTO oa_users (email, name, display_name, avatar, department, role, openid, wx_user_id, last_login_at)
      VALUES (
        ${info.email},
        ${info.name},
        ${info.display_name || info.name},
        ${info.avatar ?? ""},
        ${dept},
        ${role},
        ${openId},
        ${wx},
        now()
      )
      RETURNING id, email, name, display_name, avatar, department, role, openid, wx_user_id, created_at, last_login_at
    `;
    return rowToPublic(inserted[0]!);
  }

  const { id, role: prevRole } = existing[0]!;
  let newRole: UserRole =
    prevRole === "admin" || prevRole === "super_admin"
      ? (prevRole as UserRole)
      : "user";
  if (isSuper) newRole = "super_admin";

  await sql`
    UPDATE oa_users SET
      name = ${info.name},
      display_name = ${info.display_name || info.name},
      avatar = ${info.avatar ?? ""},
      department = ${dept},
      openid = ${openId},
      wx_user_id = ${wx},
      last_login_at = now(),
      updated_at = now(),
      role = ${newRole}
    WHERE id = ${id}::uuid
  `;
  const u = await getUserById(sql, id);
  return u!;
}

export async function getOrCreateDevUser(sql: Sql): Promise<OaUserPublic> {
  const email = getOaDevUserEmail();
  const rows = await sql<
    {
      id: string;
      email: string;
      name: string;
      display_name: string;
      avatar: string;
      department: string;
      role: string;
      openid: string | null;
      wx_user_id: string;
      created_at: Date;
      last_login_at: Date | null;
    }[]
  >`
    SELECT id, email, name, display_name, avatar, department, role, openid, wx_user_id, created_at, last_login_at
    FROM oa_users WHERE email = ${email} LIMIT 1
  `;

  if (rows.length > 0) {
    await sql`
      UPDATE oa_users SET
        name = 'Dev User',
        display_name = '开发用户',
        last_login_at = now(),
        updated_at = now(),
        role = 'super_admin'
      WHERE id = ${rows[0]!.id}::uuid
    `;
    const u = await getUserById(sql, rows[0]!.id);
    return u!;
  }

  const newId = devUserIdFromEmail(email);
  const inserted = await sql<
    {
      id: string;
      email: string;
      name: string;
      display_name: string;
      avatar: string;
      department: string;
      role: string;
      openid: string | null;
      wx_user_id: string;
      created_at: Date;
      last_login_at: Date | null;
    }[]
  >`
    INSERT INTO oa_users (id, email, name, display_name, avatar, department, role, openid, wx_user_id, last_login_at)
    VALUES (
      ${newId}::uuid,
      ${email},
      'Dev User',
      '开发用户',
      '',
      '',
      'super_admin',
      null,
      '',
      now()
    )
    RETURNING id, email, name, display_name, avatar, department, role, openid, wx_user_id, created_at, last_login_at
  `;
  return rowToPublic(inserted[0]!);
}

export async function createSession(
  sql: Sql,
  userId: string,
): Promise<{ id: string; maxAgeSeconds: number }> {
  const id = randomUUID();
  const ms = getOaAuthSessionExpiryMs();
  const maxAgeSeconds = Math.max(60, Math.floor(ms / 1000));
  const expires = new Date(Date.now() + ms);

  await sql`
    INSERT INTO oa_sessions (id, user_id, expires_at, last_seen_at)
    VALUES (${id}, ${userId}::uuid, ${expires}, now())
  `;

  return { id, maxAgeSeconds };
}

export async function revokeSession(
  sql: Sql,
  sessionId: string,
): Promise<void> {
  await sql`
    UPDATE oa_sessions SET revoked_at = now(), updated_at = now()
    WHERE id = ${sessionId} AND revoked_at IS NULL
  `;
}
