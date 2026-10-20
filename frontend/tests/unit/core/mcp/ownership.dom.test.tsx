import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const auth = rs.hoisted(() => ({ user: { id: "alice", system_role: "user" } }));
rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: () => auth }));
rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));

import { fetch } from "@/core/api/fetcher";
import { useMCPConfig } from "@/core/mcp/hooks";

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("personal MCP ownership", () => {
  it("does not display a previous account's late response after switching users", async () => {
    auth.user = { id: "alice", system_role: "user" };
    let finishAlice!: (response: Response) => void;
    rs.mocked(fetch).mockImplementation(async () => {
      if (auth.user.id === "alice") {
        return new Promise<Response>((resolve) => {
          finishAlice = resolve;
        });
      }
      return new Response(
        JSON.stringify({ mcp_servers: { "bob-only": { enabled: true } } }),
      );
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const hook = renderHook(() => useMCPConfig(), { wrapper });
    await waitFor(() => expect(finishAlice).toBeDefined());
    auth.user = { id: "bob", system_role: "user" };
    hook.rerender();
    await waitFor(() =>
      expect(hook.result.current.config?.mcp_servers).toHaveProperty(
        "bob-only",
      ),
    );
    finishAlice(
      new Response(
        JSON.stringify({ mcp_servers: { "alice-only": { enabled: true } } }),
      ),
    );
    await waitFor(() =>
      expect(client.getQueryData(["mcpConfig", "user", "alice"])).toBeDefined(),
    );
    expect(hook.result.current.config?.mcp_servers).not.toHaveProperty(
      "alice-only",
    );
    expect(hook.result.current.config?.mcp_servers).toHaveProperty("bob-only");
    expect(
      rs
        .mocked(fetch)
        .mock.calls.every(
          ([url]) =>
            typeof url === "string" && url.endsWith("/api/mcp/personal/config"),
        ),
    ).toBe(true);
    client.clear();
  });
});

describe("deployment MCP ownership", () => {
  it("separates an administrator's deployment and personal queries", async () => {
    auth.user = { id: "admin", system_role: "admin" };
    rs.mocked(fetch).mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify({
            mcp_servers: {
              github: {
                enabled: false,
                description:
                  typeof url === "string" && url.includes("/personal/")
                    ? "Personal"
                    : "Platform",
              },
            },
          }),
        ),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const hook = renderHook(
      () => ({
        personal: useMCPConfig(),
        platform: useMCPConfig("deployment"),
      }),
      { wrapper },
    );
    await waitFor(() => {
      expect(
        hook.result.current.personal.config?.mcp_servers.github?.description,
      ).toBe("Personal");
      expect(
        hook.result.current.platform.config?.mcp_servers.github?.description,
      ).toBe("Platform");
    });
    expect(client.getQueryData(["mcpConfig", "user", "admin"])).toBeDefined();
    expect(
      client.getQueryData(["mcpConfig", "deployment", "admin"]),
    ).toBeDefined();
    auth.user = { id: "member", system_role: "user" };
    hook.rerender();
    await waitFor(() =>
      expect(hook.result.current.personal.config).toBeDefined(),
    );
    expect(hook.result.current.platform.config).toBeUndefined();
    expect(
      rs
        .mocked(fetch)
        .mock.calls.filter(
          ([url]) => typeof url === "string" && url.endsWith("/api/mcp/config"),
        ),
    ).toHaveLength(1);
    client.clear();
  });
});
