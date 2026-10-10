import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { type User } from "./types";

/**
 * Admin user-management surface (RFC #4063 gap 3).
 *
 * The Gateway list/update endpoints return the same UserResponse shape as
 * ``/auth/me`` (id, email, system_role, needs_setup, oauth_provider,
 * disabled), so the parsed User type is reused verbatim. ``disabled`` is
 * optional in the schema — absent means not disabled — and every writer
 * here sends it explicitly, so the rows this module refreshes always
 * carry it.
 */
export type AdminUser = User;

/** Partial account update accepted by PATCH /api/v1/admin/users/{id}. */
export interface UserAccountUpdate {
  system_role?: string;
  disabled?: boolean;
}

async function request<T>(
  suffix: string,
  method: "GET" | "PATCH",
  body?: UserAccountUpdate,
  signal?: AbortSignal,
): Promise<T> {
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
  return response.json() as Promise<T>;
}

export const loadAdminUsers = (signal?: AbortSignal) =>
  request<AdminUser[]>("", "GET", undefined, signal);

export const updateUserAccount = (
  userId: string,
  update: UserAccountUpdate,
) => request<AdminUser>(`/${encodeURIComponent(userId)}`, "PATCH", update);
