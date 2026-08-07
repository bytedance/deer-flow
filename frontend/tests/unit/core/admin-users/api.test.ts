import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

import {
  AdminUsersRequestError,
  changeAdminUserRole,
  listAdminUsers,
} from "@/core/admin-users/api";
import { fetch as fetcher } from "@/core/api/fetcher";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

const adminUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "admin@example.com",
  system_role: "admin" as const,
  created_at: "2026-07-31T06:30:00Z",
  needs_setup: false,
  oauth_provider: null,
};

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("admin users API", () => {
  test("loads the user list contract", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { users: [adminUser], total: 1 }),
    );

    await expect(listAdminUsers()).resolves.toEqual({
      users: [adminUser],
      total: 1,
    });
    expect(mockedFetch).toHaveBeenCalledWith("/api/v1/admin/users");
  });

  test("loads every page when the first response is truncated", async () => {
    const secondUser = {
      ...adminUser,
      id: "00000000-0000-0000-0000-000000000002",
      email: "user@example.com",
      system_role: "user" as const,
    };
    mockedFetch
      .mockResolvedValueOnce(
        jsonResponse(200, { users: [adminUser], total: 2 }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { users: [secondUser], total: 2 }),
      );

    await expect(listAdminUsers()).resolves.toEqual({
      users: [adminUser, secondUser],
      total: 2,
    });
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/admin/users?offset=1&limit=200",
    );
  });

  test("patches an encoded user id with the requested role", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        user: { ...adminUser, system_role: "user" },
        previous_role: "admin",
        sessions_invalidated: true,
      }),
    );

    await expect(
      changeAdminUserRole("user/with space", "user"),
    ).resolves.toMatchObject({
      user: { system_role: "user" },
      previous_role: "admin",
      sessions_invalidated: true,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/v1/admin/users/user%2Fwith%20space/role",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_role: "user" }),
      },
    );
  });

  test("preserves structured FastAPI detail errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(409, {
        detail: {
          code: "last_admin",
          message: "The last administrator cannot be demoted.",
        },
      }),
    );

    const promise = changeAdminUserRole(adminUser.id, "user");
    await expect(promise).rejects.toMatchObject({
      name: "AdminUsersRequestError",
      status: 409,
      code: "last_admin",
      message: "The last administrator cannot be demoted.",
    });
    await expect(promise).rejects.toBeInstanceOf(AdminUsersRequestError);
  });

  test("supports legacy string detail errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Admin privileges required." }),
    );

    await expect(listAdminUsers()).rejects.toMatchObject({
      status: 403,
      code: null,
      isAdminRequired: true,
      message: "Admin privileges required.",
    });
  });

  test("rejects a malformed success payload", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { users: [] }));

    await expect(listAdminUsers()).rejects.toThrow();
  });
});
