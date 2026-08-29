import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { CreatePatRequest, PatCreated, PatSummary } from "./types";

async function errorDetail(res: Response, fallback: string): Promise<string> {
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    const messages = body.detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String(item.msg)
          : null,
      )
      .filter((message): message is string => message !== null);
    if (messages.length > 0) return messages.join("; ");
  }
  return fallback;
}

export class PatStoreUnavailableError extends Error {
  constructor() {
    super("pat store unavailable");
    this.name = "PatStoreUnavailableError";
  }
}

export async function listPats(): Promise<PatSummary[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/v1/auth/pats`);
  if (!res.ok) {
    if (res.status === 503) throw new PatStoreUnavailableError();
    throw new Error(await errorDetail(res, "Failed to load tokens"));
  }
  return res.json() as Promise<PatSummary[]>;
}

export async function createPat(
  request: CreatePatRequest,
): Promise<PatCreated> {
  const res = await fetch(`${getBackendBaseURL()}/api/v1/auth/pats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    if (res.status === 503) throw new PatStoreUnavailableError();
    throw new Error(await errorDetail(res, "Failed to create token"));
  }
  return res.json() as Promise<PatCreated>;
}

export async function revokePat(patId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/v1/auth/pats/${encodeURIComponent(patId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    if (res.status === 503) throw new PatStoreUnavailableError();
    throw new Error(await errorDetail(res, "Failed to revoke token"));
  }
}
