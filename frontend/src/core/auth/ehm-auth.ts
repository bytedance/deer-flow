import { type User } from "./types";

export const EHM_TOKEN_COOKIE = "ehm_token";
export const EHM_USER_COOKIE = "ehm_user";

interface EhmTokenPayload {
  id: number;
  exp: number;
  iat: number;
}

interface EhmUserInfo {
  id: string;
  user_name: string;
  real_name: string;
  org_id: string;
}

function base64UrlDecode(str: string): string {
  const base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  if (typeof atob !== "undefined") {
    return atob(base64);
  }
  return Buffer.from(base64, "base64").toString("utf-8");
}

/**
 * Decode the payload of a JWT without verifying the signature.
 * Returns null only if the token is structurally malformed (not 3 parts,
 * base64 decode fails, or JSON parse fails). Accepts any identifier shape
 * in the payload — ins-base JWTs may carry id, userId, or sub.
 */
function decodeJwtPayload(token: string): EhmTokenPayload | null {
  try {
    const parts = token.split(".");
    const encodedPayload = parts[1];
    if (parts.length !== 3 || !encodedPayload) return null;
    const payload = JSON.parse(base64UrlDecode(encodedPayload));
    if (typeof payload !== "object" || payload === null) return null;
    return payload as EhmTokenPayload;
  } catch {
    return null;
  }
}

function base64Decode(str: string): string {
  if (typeof atob !== "undefined") {
    return atob(str);
  }
  return Buffer.from(str, "base64").toString("utf-8");
}

function readClientCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(`${name}=`)) {
      return decodeURIComponent(pair.slice(name.length + 1));
    }
  }
  return null;
}

/**
 * Build a User object from EHM user info stored in cookie.
 * Returns null if the cookie is missing or malformed.
 */
export function getServerEhmUser(cookieStore: {
  get(name: string): { value: string } | undefined;
}): User | null {
  const userCookie = cookieStore.get(EHM_USER_COOKIE);
  if (!userCookie) return null;
  try {
    const info: EhmUserInfo = JSON.parse(base64Decode(userCookie.value));
    if (!info.id || !info.user_name) return null;
    return {
      id: info.id,
      email: `${info.user_name}@ehm.local`,
      system_role: "user",
      tenant_id: info.org_id || "default",
      user_name: info.user_name,
      real_name: info.real_name || "",
    };
  } catch {
    return null;
  }
}

/**
 * Check whether the given token is still valid (not expired).
 * Returns true when the token cannot be decoded or has no exp claim —
 * the server is the final authority on validity.
 */
export function isEhmTokenValid(token: string): boolean {
  const payload = decodeJwtPayload(token);
  if (!payload) return true;
  if (typeof payload.exp !== "number") return true;
  return payload.exp * 1000 > Date.now();
}

/**
 * Check only whether the token's exp claim has passed.
 * Returns false when the token cannot be decoded (let the server decide).
 */
export function isEhmTokenExpired(token: string): boolean {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") return false;
  return payload.exp * 1000 <= Date.now();
}

/**
 * Server-side: extract EHM token from cookies.
 */
export function getServerEhmToken(
  cookieStore: Awaited<ReturnType<typeof import("next/headers").cookies>>
): string | null {
  const cookie = cookieStore.get(EHM_TOKEN_COOKIE);
  if (!cookie) return null;
  const token = cookie.value;
  if (!isEhmTokenValid(token)) return null;
  return token;
}

/**
 * Client-side: read the EHM token from cookies.
 */
export function getClientEhmToken(): string | null {
  return readClientCookie(EHM_TOKEN_COOKIE);
}

/**
 * Client-side: check if an EHM token cookie exists.
 */
export function hasClientEhmToken(): boolean {
  return getClientEhmToken() !== null;
}

/**
 * Client-side: set the EHM token and user info cookies.
 */
export function setEhmCookies(token: string, userInfoBase64?: string): void {
  document.cookie = `${EHM_TOKEN_COOKIE}=${token}; path=/; SameSite=Lax; max-age=86400`;
  if (userInfoBase64) {
    document.cookie = `${EHM_USER_COOKIE}=${userInfoBase64}; path=/; SameSite=Lax; max-age=86400`;
  }
}

/**
 * Client-side: clear all EHM cookies.
 */
export function clearEhmCookies(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${EHM_TOKEN_COOKIE}=; path=/; max-age=0`;
  document.cookie = `${EHM_USER_COOKIE}=; path=/; max-age=0`;
}

/**
 * Client-side: set the EHM token and user info cookies, then redirect.
 */
export function setEhmCookieAndRedirect(
  token: string,
  targetPath: string,
  userInfoBase64?: string,
) {
  setEhmCookies(token, userInfoBase64);
  window.location.href = targetPath;
}
