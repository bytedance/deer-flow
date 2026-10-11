import { z } from "zod";

import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { type User, userSchema } from "./types";

/**
 * Admin user-management surface (RFC #4063 gap 3).
 *
 * The Gateway list/update endpoints return the same UserResponse shape as
 * ``/auth/me`` (id, email, system_role, needs_setup, oauth_provider,
 * disabled), so ``userSchema`` is reused verbatim — both payloads are
 * parsed, and a malformed body (dropped id, non-boolean disabled) rejects
 * into the caller's error path instead of rendering a phantom row.
 * ``disabled`` is optional in the schema — absent means not disabled — and
 * every writer here sends it explicitly, so the rows this module refreshes
 * always carry it.
 */
export type AdminUser = User;

const adminUserArraySchema = z.array(userSchema);

/** Partial account update accepted by PATCH /api/v1/admin/users/{id}. */
export interface UserAccountUpdate {
  system_role?: string;
  disabled?: boolean;
}

async function request(
  suffix: string,
  method: "GET" | "PATCH",
  body?: UserAccountUpdate,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/v1/admin/users${suffix}`,
    {
      method,
      signal,
      ...(body
        ? {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        : {}),
    },
  );
  if (!response.ok)
    await throwGatewayApiError(response, "Admin user request failed");
  return response.json();
}

export const loadAdminUsers = (signal?: AbortSignal): Promise<AdminUser[]> =>
  request("", "GET", undefined, signal).then((data) =>
    adminUserArraySchema.parse(data),
  );

export const updateUserAccount = (
  userId: string,
  update: UserAccountUpdate,
): Promise<AdminUser> =>
  request(`/${encodeURIComponent(userId)}`, "PATCH", update).then((data) =>
    userSchema.parse(data),
  );
