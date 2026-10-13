import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  remove: rs.fn(),
  search: rs.fn(),
  fetch: rs.fn(),
}));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: { delete: mocks.remove, search: mocks.search },
  }),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));

import { useDeleteThread } from "@/core/threads/hooks";

beforeEach(() => {
  mocks.remove.mockReset().mockResolvedValue(undefined);
  mocks.search.mockReset().mockResolvedValue([]);
  mocks.fetch
    .mockReset()
    .mockImplementation(async () => new Response(null, { status: 204 }));
});
afterEach(cleanup);

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useDeleteThread(), { wrapper });
}

test("cleanup failure does not invoke completion and a remote 404 retry finishes cleanup", async () => {
  const onDeleted = rs.fn();
  const { result } = setup();
  mocks.fetch.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "Cleanup unavailable" }), {
      status: 500,
    }),
  );
  await act(async () => {
    await expect(
      result.current.mutateAsync({ threadId: "parent", onDeleted }),
    ).rejects.toThrow("Cleanup unavailable");
  });
  expect(onDeleted).not.toHaveBeenCalled();
  mocks.remove.mockRejectedValueOnce(
    Object.assign(new Error("Thread not found"), { status: 404 }),
  );
  await act(async () => {
    await result.current.mutateAsync({ threadId: "parent", onDeleted });
  });
  expect(mocks.fetch).toHaveBeenCalledTimes(2);
  expect(onDeleted).toHaveBeenCalledTimes(1);
});

for (const status of [403, 500]) {
  test(`remote ${status} stays an error and never starts local cleanup`, async () => {
    const onDeleted = rs.fn();
    mocks.remove.mockRejectedValueOnce({ status });
    const { result } = setup();
    await act(async () => {
      await expect(
        result.current.mutateAsync({ threadId: "parent", onDeleted }),
      ).rejects.toEqual({ status });
    });
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });
}

test("already-deleted sidecars still receive local cleanup", async () => {
  mocks.search.mockResolvedValueOnce([
    {
      thread_id: "sidecar",
      metadata: { deerflow_sidecar: true, parent_thread_id: "parent" },
    },
  ]);
  mocks.remove.mockRejectedValueOnce(
    Object.assign(new Error("Thread not found"), { response: { status: 404 } }),
  );
  const { result } = setup();
  await act(async () => {
    await expect(
      result.current.mutateAsync({ threadId: "parent" }),
    ).resolves.toEqual(["sidecar"]);
  });
  expect(mocks.fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/sidecar"),
    { method: "DELETE" },
  );
  expect(mocks.fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/parent"),
    { method: "DELETE" },
  );
});
