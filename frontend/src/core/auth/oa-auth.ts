"use client";

/** Mirrors the OA auth user payload (``/api/auth/me`` → ``data``). */
export type OaAuthUser = {
  id: string;
  email: string;
  name: string;
  displayName: string;
  avatar?: string;
  department?: string;
  role: "user" | "admin" | "super_admin";
  createdAt?: string;
  lastLoginAt?: string;
};

export { isOaAuthEnabled } from "@/core/auth/oa-auth-flags";

/** OA routes live under ``/user/oa-auth/*`` (not ``/api/*``, which is proxied to the backend). */
const OA_AUTH_BASE = "/user/oa-auth";

export function getCurrentPath(): string {
  if (typeof window === "undefined") return "/workspace";
  const { pathname, search, hash } = window.location;
  return `${pathname}${search}${hash}`;
}

/**
 * Same pattern as the previous SSO login helper. SSO lives at ``/user/oa-auth/*`` so it does not
 * collide with better-auth at ``/api/auth/*`` or with gateway-backed ``/api/*``.
 */
export function getOaAuthLoginURL(path: string): string {
  const redirect = path && path.length > 0 ? path : "/workspace";
  return `${OA_AUTH_BASE}/login?redirect=${encodeURIComponent(redirect)}`;
}

/** Default post-login landing for the DeerFlow workspace. */
export function getDefaultAgentChatPath(): string {
  return "/workspace";
}

function parseMePayload(json: unknown): OaAuthUser | null {
  if (!json || typeof json !== "object") return null;
  const o = json as Record<string, unknown>;
  const data = (o.data ?? o) as Record<string, unknown>;
  const id = data.id;
  const email = data.email;
  if (typeof id !== "string" || typeof email !== "string") return null;
  const role = data.role;
  return {
    id,
    email,
    name: typeof data.name === "string" ? data.name : "",
    displayName:
      typeof data.displayName === "string"
        ? data.displayName
        : typeof data.display_name === "string"
          ? data.display_name
          : "",
    avatar: typeof data.avatar === "string" ? data.avatar : undefined,
    department:
      typeof data.department === "string" ? data.department : undefined,
    role:
      role === "admin" || role === "super_admin" || role === "user"
        ? role
        : "user",
    createdAt: typeof data.createdAt === "string" ? data.createdAt : undefined,
    lastLoginAt:
      typeof data.lastLoginAt === "string" ? data.lastLoginAt : undefined,
  };
}

export async function fetchOaAuthMe(init?: RequestInit): Promise<OaAuthUser> {
  const res = await fetch(`${OA_AUTH_BASE}/me`, {
    credentials: "include",
    ...init,
    headers: {
      accept: "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const err = new Error(`oa-auth me failed: ${res.status}`) as Error & {
      status: number;
    };
    err.status = res.status;
    throw err;
  }
  const json: unknown = await res.json();
  const user = parseMePayload(json);
  if (!user) {
    throw new Error("oa-auth me: unexpected response shape");
  }
  return user;
}

export async function fetchOaAuthMeSilently(): Promise<OaAuthUser> {
  return fetchOaAuthMe();
}

export async function oaAuthLogout(): Promise<void> {
  await fetch(`${OA_AUTH_BASE}/logout`, {
    method: "POST",
    credentials: "include",
  });
}
