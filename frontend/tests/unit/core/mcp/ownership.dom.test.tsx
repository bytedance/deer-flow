import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const auth = rs.hoisted(() => ({ user: { id: "alice" } }));
rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: () => auth }));
rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));

import { fetch } from "@/core/api/fetcher";
import { useMCPConfig } from "@/core/mcp/hooks";

afterEach(cleanup);

describe("personal MCP ownership", () => {
  it("does not display a previous account's late response after switching users", async () => {
    auth.user = { id: "alice" };
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
    auth.user = { id: "bob" };
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
