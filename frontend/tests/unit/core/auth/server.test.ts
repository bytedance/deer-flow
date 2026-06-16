import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  cookies: vi.fn(),
  getGatewayConfig: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: mocks.cookies,
}));

vi.mock("@/core/auth/gateway-config", () => ({
  getGatewayConfig: mocks.getGatewayConfig,
}));

async function loadFreshServerModule() {
  vi.resetModules();
  return await import("@/core/auth/server");
}

describe("getServerSideUser", () => {
  beforeEach(() => {
    mocks.cookies.mockReset();
    mocks.getGatewayConfig.mockReset();
    mocks.getGatewayConfig.mockReturnValue({
      internalGatewayUrl: "http://127.0.0.1:8001",
      trustedOrigins: ["http://localhost:3000"],
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("forwards refresh_token alongside access_token for SSR auth refresh", async () => {
    const cookieStore = {
      get: vi.fn((name: string) => {
        if (name === "access_token") return { value: "access-123" };
        if (name === "refresh_token") return { value: "refresh-456" };
        return undefined;
      }),
    };

    mocks.cookies.mockResolvedValue(cookieStore);

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          id: "user-1",
          email: "alice@example.com",
          system_role: "user",
          tenant_id: "tenant-a",
          user_name: "alice",
          real_name: "Alice",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { getServerSideUser } = await loadFreshServerModule();
    const result = await getServerSideUser();

    expect(result.tag).toBe("authenticated");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8001/api/v1/auth/me",
      expect.objectContaining({
        headers: {
          Cookie: "access_token=access-123; refresh_token=refresh-456",
        },
      }),
    );
  });
});
