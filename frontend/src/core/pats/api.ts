import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { CreatePatRequest, PatCreated, PatSummary } from "./types";

export class PatStoreUnavailableError extends Error {
  constructor() {
    super("pat store unavailable");
    this.name = "PatStoreUnavailableError";
  }
}

/**
 * The backend's identity fence rejected the declared identity: this tab's
 * React auth state (user id + session generation, both from /me) disagrees
 * with the account the shared session cookie now authenticates — typically
 * another tab signed in meanwhile. No PAT data crossed the boundary.
 */
export class StaleSessionIdentityError extends Error {
  constructor() {
    super("Session identity changed");
    this.name = "StaleSessionIdentityError";
  }
}

export type SessionIdentity = {
  userId: string;
  generation: number | null;
};

/**
 * The identity a browser PAT request must be able to declare in full: user
 * id plus a non-null session generation from /me. An undeclared request is
 * deliberately admitted by the backend as a non-browser client (curl flows)
 * — which is exactly why the browser must never send one.
 */
export type DeclaredSessionIdentity = {
  userId: string;
  generation: number;
};

export const SESSION_IDENTITY_HEADER = "X-DF-Session";

/**
 * A browser PAT operation was attempted before /me established the
 * fence-able identity (no user, or no session generation yet). Held at the
 * hooks layer so an undeclared request cannot leak the cookie's current
 * account into a stale tab.
 */
export class MissingSessionIdentityError extends Error {
  constructor() {
    super("Session identity unavailable");
    this.name = "MissingSessionIdentityError";
  }
}

/**
 * The declaration the backend compares against the authenticated session.
 * Sent only when /me provided a generation; a null generation (SSR literal,
 * non-session source) omits the header, which the backend treats as an
 * undeclared client (curl flows) rather than a fence violation.
 */
export function sessionIdentityHeaders(
  identity: SessionIdentity | null | undefined,
): Record<string, string> {
  if (identity?.generation == null) {
    return {};
  }
  return {
    [SESSION_IDENTITY_HEADER]: `${identity.userId}:${identity.generation}`,
  };
}

/**
 * The creation POST already passed the backend fence for the initiating
 * account, but this tab's session changed before the result resolved
 * (another tab replaced the shared cookie). The show-once token belongs to
 * the initiating account and must not be rendered inside the successor's
 * settings UI, so the result is withheld and the credential stays
 * discoverable only through the initiating account's token list.
 */
export class SessionChangedDuringCreateError extends Error {
  constructor() {
    super("Session changed while creating the token");
    this.name = "SessionChangedDuringCreateError";
  }
}

// The one 503 that means "this deployment has no PAT store": deps.py's
// get_pat_repo raises it verbatim when the process runs on the memory
// backend. Any other 503 (reverse proxy, load balancer, briefly overloaded
// gateway) is transient and must not pin the page to the permanent
// store-unavailable banner.
const PAT_STORE_UNAVAILABLE_DETAIL =
  "Personal access tokens require a configured database";

async function throwForPatFailure(res: Response, fallback: string) {
  if (res.status === 503) {
    const body = (await res.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    if (body?.detail === PAT_STORE_UNAVAILABLE_DETAIL) {
      throw new PatStoreUnavailableError();
    }
    throw new Error(
      typeof body?.detail === "string" ? body.detail : fallback,
    );
  }
  if (res.status === 409) {
    const body = (await res.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    if (
      typeof body?.detail === "string" &&
      body.detail.startsWith("Session identity changed")
    ) {
      throw new StaleSessionIdentityError();
    }
  }
  await throwGatewayApiError(res, fallback);
}

export async function listPats(
  identity?: SessionIdentity | null,
): Promise<PatSummary[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/v1/auth/pats`, {
    headers: sessionIdentityHeaders(identity),
  });
  if (!res.ok) {
    await throwForPatFailure(res, "Failed to load tokens");
  }
  return res.json() as Promise<PatSummary[]>;
}

export async function createPat(
  request: CreatePatRequest,
  identity?: SessionIdentity | null,
): Promise<PatCreated> {
  const res = await fetch(`${getBackendBaseURL()}/api/v1/auth/pats`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...sessionIdentityHeaders(identity),
    },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    await throwForPatFailure(res, "Failed to create token");
  }
  return res.json() as Promise<PatCreated>;
}

export async function revokePat(
  patId: string,
  identity?: SessionIdentity | null,
): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/v1/auth/pats/${encodeURIComponent(patId)}`,
    {
      method: "DELETE",
      headers: sessionIdentityHeaders(identity),
    },
  );
  if (!res.ok) {
    await throwForPatFailure(res, "Failed to revoke token");
  }
}
