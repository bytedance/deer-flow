import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

import { GatewayApiError } from "@/core/api/errors";
import { loadAdminUsers, updateUserAccount } from "@/core/auth/admin-users";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("admin user management client", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test("loadAdminUsers requests the admin list endpoint", async () => {
    const fetchSpy = rs.fn(async () =>
      jsonResponse([
        {
          id: "u-1",
          email: "a@example.com",
          system_role: "admin",
          needs_setup: false,
          oauth_provider: null,
          disabled: true,
        },
      ]),
    );
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch;

    const users = await loadAdminUsers();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/admin/users",
      expect.objectContaining({ method: "GET" }),
    );
    expect(users).toEqual([
      {
        id: "u-1",
        email: "a@example.com",
        system_role: "admin",
        needs_setup: false,
        oauth_provider: null,
        disabled: true,
      },
    ]);
  });

  test("updateUserAccount PATCHes a JSON body with only the changed fields", async () => {
    const fetchSpy = rs.fn(async () =>
      jsonResponse({
        id: "u-1",
        email: "a@example.com",
        system_role: "admin",
        needs_setup: false,
        oauth_provider: null,
        disabled: true,
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch;

    await updateUserAccount("u 1/id", { disabled: true });

    const [url, init] = rs.mocked(fetchSpy).mock.calls[0] as unknown as [
      string,
      RequestInit & { body: string },
    ];
    expect(url).toBe("/api/v1/admin/users/u%201%2Fid");
    expect(init.method).toBe("PATCH");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({ disabled: true });
  });

  test("a 409 conflict surfaces the gateway detail as the error message", async () => {
    globalThis.fetch = rs.fn(async () =>
      jsonResponse(
        { detail: "cannot disable the last remaining active admin" },
        409,
      ),
    ) as unknown as typeof globalThis.fetch;

    const error = await updateUserAccount("u-1", { disabled: true }).catch(
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(GatewayApiError);
    expect(error).toMatchObject({
      status: 409,
      message: "cannot disable the last remaining active admin",
    });
  });

  test("a coded-envelope 409 still surfaces its message verbatim", async () => {
    globalThis.fetch = rs.fn(async () =>
      jsonResponse(
        {
          detail: {
            code: "last_active_admin",
            message: "cannot disable the last remaining active admin",
          },
        },
        409,
      ),
    ) as unknown as typeof globalThis.fetch;

    const error = await updateUserAccount("u-1", { disabled: true }).catch(
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(GatewayApiError);
    expect(error).toMatchObject({
      status: 409,
      message: "cannot disable the last remaining active admin",
    });
  });

  test("a malformed row rejects instead of rendering a phantom user", async () => {
    globalThis.fetch = rs.fn(async () =>
      jsonResponse([{ email: "no-id@example.com" }]),
    ) as unknown as typeof globalThis.fetch;

    await expect(loadAdminUsers()).rejects.toThrow();
  });
});
