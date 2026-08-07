import { fetch } from "@/core/api/fetcher";
import type { SystemRole } from "@/core/auth/types";

import {
  adminUserRoleChangeResponseSchema,
  adminUsersResponseSchema,
  type AdminUserRoleChangeResponse,
  type AdminUsersResponse,
} from "./types";

export class AdminUsersRequestError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = "AdminUsersRequestError";
    this.status = status;
    this.code = code;
  }

  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

async function readError(
  response: Response,
  fallback: string,
): Promise<{ code: string | null; message: string }> {
  const body = (await response.json().catch(() => ({}))) as {
    code?: unknown;
    message?: unknown;
    detail?: unknown;
  };
  const detail = body.detail;
  if (typeof detail === "object" && detail !== null) {
    const code = Reflect.get(detail, "code");
    const message = Reflect.get(detail, "message");
    if (typeof message === "string") {
      return {
        code: typeof code === "string" ? code : null,
        message,
      };
    }
  }
  if (typeof detail === "string") {
    return { code: null, message: detail };
  }
  if (typeof body.message === "string") {
    return {
      code: typeof body.code === "string" ? body.code : null,
      message: body.message,
    };
  }
  return { code: null, message: fallback };
}

async function throwAdminUsersError(
  response: Response,
  fallback: string,
): Promise<never> {
  const error = await readError(response, fallback);
  throw new AdminUsersRequestError(response.status, error.code, error.message);
}

async function listAdminUsersPage(url: string): Promise<AdminUsersResponse> {
  const response = await fetch(url);
  if (!response.ok) {
    await throwAdminUsersError(response, "Failed to load users");
  }
  return adminUsersResponseSchema.parse(await response.json());
}

export async function listAdminUsers(): Promise<AdminUsersResponse> {
  const firstPage = await listAdminUsersPage("/api/v1/admin/users");
  const users = [...firstPage.users];
  let total = firstPage.total;

  // The settings page searches and calculates its advisory last-admin state
  // client-side, so it needs the complete list rather than silently stopping
  // at the API's default page size. The repository still caps each request.
  while (users.length < total) {
    const page = await listAdminUsersPage(
      `/api/v1/admin/users?offset=${users.length}&limit=200`,
    );
    if (page.users.length === 0) {
      throw new Error("Admin user pagination ended before the reported total");
    }
    users.push(...page.users);
    total = page.total;
  }

  return { users, total };
}

export async function changeAdminUserRole(
  userId: string,
  systemRole: SystemRole,
): Promise<AdminUserRoleChangeResponse> {
  const response = await fetch(
    `/api/v1/admin/users/${encodeURIComponent(userId)}/role`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_role: systemRole }),
    },
  );
  if (!response.ok) {
    await throwAdminUsersError(response, "Failed to change user role");
  }
  return adminUserRoleChangeResponseSchema.parse(await response.json());
}
