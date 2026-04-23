import { env } from "@/env";

import {
  normalizeOAuthCallbackUrl,
} from "@/server/oa-auth/callback-url";

function truthyEnv(v: string | undefined): boolean {
  if (!v) return false;
  const s = v.trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes";
}

function firstNonEmpty(...candidates: (string | undefined)[]): string | undefined {
  for (const c of candidates) {
    const t = c?.trim();
    if (t) return t;
  }
  return undefined;
}

export function getOaAuthDatabaseUrl(): string | undefined {
  return firstNonEmpty(
    env.OA_AUTH_DATABASE_URL,
    env.DEERFLOW_POSTGRES_URL,
    env.DATABASE_URL,
  );
}

/**
 * ``DEV_MODE=true`` 时 ``GET /user/oa-auth/login`` 自动以开发用户登录；
 * 也可用 ``OA_AUTH_DEV_MODE=true``（DeerFlow 专用名）。
 */
export function isOaAuthDevMode(): boolean {
  return truthyEnv(env.OA_AUTH_DEV_MODE) || truthyEnv(env.DEV_MODE);
}

export function getOaAuthSessionCookieName(): string {
  return firstNonEmpty(env.OA_AUTH_SESSION_COOKIE_NAME) ?? "deerflow_oa_session";
}

export function getOaAuthSessionExpiryMs(): number {
  const raw = env.OA_AUTH_SESSION_EXPIRY?.trim();
  if (!raw) return 12 * 60 * 60 * 1000;
  const m = /^(\d+)(ms|s|m|h|d)$/i.exec(raw);
  if (!m?.[1] || !m[2]) return 12 * 60 * 60 * 1000;
  const n = Number(m[1]);
  const u = m[2].toLowerCase();
  const mult =
    u === "ms" ? 1 : u === "s" ? 1000 : u === "m" ? 60_000 : u === "h" ? 3_600_000 : 86_400_000;
  return n * mult;
}

export function getOAuthBaseUrl(): string {
  const t = firstNonEmpty(env.OA_OAUTH_BASE_URL);
  if (!t) {
    throw new Error("OA_OAUTH_BASE_URL is required");
  }
  return t.replace(/\/+$/, "");
}

export function getOAuthClientId(): string {
  return firstNonEmpty(env.OA_OAUTH_CLIENT_ID) ?? "";
}

export function getOAuthClientSecret(): string {
  return firstNonEmpty(env.OA_OAUTH_CLIENT_SECRET) ?? "";
}

export function getOAuthCallbackUrl(): string {
  const raw = firstNonEmpty(env.OA_OAUTH_CALLBACK_URL) ?? "";
  if (!raw) return "";
  try {
    return normalizeOAuthCallbackUrl(raw);
  } catch {
    return raw.trim();
  }
}

/**
 * Public site origin for server redirects after OAuth. Prefer this over ``request.url`` so
 * redirects work behind reverse proxies that expose ``localhost`` / internal hosts to Node.
 */
export function getOaAuthPublicRedirectOrigin(): string | undefined {
  const callback = getOAuthCallbackUrl();
  if (!callback) return undefined;
  try {
    return new URL(callback).origin;
  } catch {
    return undefined;
  }
}

export function getOaSuperAdminEmail(): string {
  return firstNonEmpty(env.OA_SUPER_ADMIN_EMAIL) ?? "";
}

/** 默认 ``DEV_USER_EMAIL``，与 ``OA_AUTH_DEV_USER_EMAIL`` 二选一。 */
export function getOaDevUserEmail(): string {
  return firstNonEmpty(env.DEV_USER_EMAIL, env.OA_AUTH_DEV_USER_EMAIL) ?? "dev@example.com";
}

export function isOaAuthCookieSecure(): boolean {
  if (env.OA_AUTH_COOKIE_SECURE !== undefined) {
    return truthyEnv(env.OA_AUTH_COOKIE_SECURE);
  }
  return env.NODE_ENV === "production";
}

export function isOAuthConfigured(): boolean {
  return Boolean(
    getOAuthClientId() &&
      getOAuthClientSecret() &&
      getOAuthCallbackUrl(),
  );
}

export function oaAuthRuntimeReady(): boolean {
  if (!getOaAuthDatabaseUrl()) return false;
  if (isOaAuthDevMode()) return true;
  return isOAuthConfigured();
}
