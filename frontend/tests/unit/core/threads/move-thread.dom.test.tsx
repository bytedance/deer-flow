import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({ fetch: rs.fn(), get: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({ threads: { get: mocks.get } }),
}));

import {
  useMoveThreadToProject,
  useThreadMetadata,
} from "@/core/threads/hooks";

const original = {
  thread_id: "chat",
  metadata: { deerflow_project_id: "project-a", deerflow_pinned: true },
};

afterEach(() => {
  cleanup();
  rs.resetAllMocks();
});

test("move updates only affiliation and marks inactive metadata stale", async () => {
  const client = new QueryClient();
  const key = ["thread", "metadata", "chat", false];
  client.setQueryData(key, original);
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ metadata: { deerflow_pinned: false } })),
  );
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result, unmount } = renderHook(() => useMoveThreadToProject(), {
    wrapper,
  });
  try {
    await act(async () => {
      await result.current.mutateAsync({
        threadId: "chat",
        projectId: "project-b",
      });
    });
    expect(client.getQueryData(key)).toEqual({
      ...original,
      metadata: { ...original.metadata, deerflow_project_id: "project-b" },
    });
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});

for (const cached of [false, true]) {
  for (const projectId of ["project-b", null]) {
    test(`move to ${projectId} fences a delayed metadata read (cached: ${cached})`, async () => {
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const key = ["thread", "metadata", "chat", false];
      if (cached) client.setQueryData(key, original);
      const moved = {
        ...original,
        metadata: { ...original.metadata, deerflow_project_id: projectId },
      };
      let finishOldRead!: (value: typeof original) => void;
      const oldRead = new Promise<typeof original>((resolve) => {
        finishOldRead = resolve;
      });
      mocks.get.mockReturnValueOnce(oldRead).mockResolvedValue(moved);
      mocks.fetch.mockResolvedValue(new Response(JSON.stringify(moved)));
      const wrapper = ({ children }: PropsWithChildren) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
      const { result, unmount } = renderHook(
        () => ({
          metadata: useThreadMetadata("chat"),
          move: useMoveThreadToProject(),
        }),
        { wrapper },
      );
      try {
        await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
        await act(async () => {
          await result.current.move.mutateAsync({
            threadId: "chat",
            projectId,
          });
        });
        await act(async () => {
          finishOldRead(original);
          await oldRead;
        });
        await waitFor(() => {
          expect(result.current.metadata.data?.metadata).toEqual(
            moved.metadata,
          );
          expect(result.current.metadata.isFetching).toBe(false);
        });
        expect(mocks.get).toHaveBeenCalledTimes(2);
        expect(client.getQueryData(key)).toEqual(moved);
      } finally {
        unmount();
        client.clear();
      }
    });
  }
}
