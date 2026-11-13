import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { useWorkspaceSearch } from "@/core/search/hooks";

let viewer = { id: "alice", permissions: ["threads:read"] };
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: viewer }),
}));
const search = rs.fn();
rs.mock("@/core/search/api", () => ({
  searchWorkspace: (...args: unknown[]) => search(...args),
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
  viewer = { id: "alice", permissions: ["threads:read"] };
});

test("debounce retains results only within the same owner, permission and filter scope", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  search.mockResolvedValueOnce({
    items: [{ type: "thread", thread_id: "old" }],
    cursor: null,
  });
  search.mockImplementation(() => new Promise(() => undefined));
  const { result, rerender } = renderHook(
    ({ query, archived }) =>
      useWorkspaceSearch(
        query,
        { type: "thread", includeArchived: archived },
        true,
      ),
    { wrapper, initialProps: { query: "old", archived: false } },
  );
  await waitFor(() => expect(result.current.items).toHaveLength(1));
  rerender({ query: "new", archived: false });
  expect(result.current.waiting).toBe(true);
  expect(result.current.items).toHaveLength(1);
  rerender({ query: "new", archived: true });
  expect(result.current.items).toHaveLength(0);
  viewer = { id: "bob", permissions: ["threads:read"] };
  rerender({ query: "old", archived: false });
  expect(result.current.items).toHaveLength(0);
  viewer = { id: "alice", permissions: [] };
  rerender({ query: "old", archived: false });
  expect(result.current.supported).toBe(false);
  expect(result.current.items).toHaveLength(0);
  client.clear();
});
