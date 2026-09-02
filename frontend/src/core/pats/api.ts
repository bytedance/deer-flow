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

export const SESSION_IDENTITY_HEADER = "X-DF-Session";

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

async function throwForPatFailure(res: Response, fallback: string) {
  if (res.status === 503) throw new PatStoreUnavailableError();
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
