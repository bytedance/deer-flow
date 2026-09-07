import { afterEach, expect, rs, test } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));

import { useArchiveThread } from "@/core/threads/archive";
import { usePinThread } from "@/core/threads/hooks";

const original = {
  thread_id: "chat",
  metadata: { deerflow_pinned: true },
  values: { title: "Report" },
  updated_at: "2026-01-01T00:00:00Z",
};
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const key = ["thread", "metadata", "chat", false];
  client.setQueryData(key, original);
  client.setQueryData(["threads", "searchInfinite", { archived: false }], {
    pages: [[original]],
    pageParams: [0],
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, key, ...renderHook(() => useArchiveThread(), { wrapper }) };
}

test("archive preserves the active snapshot and resets list pagination after success", async () => {
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ metadata: { deerflow_archived: true } })),
  );
  const { client, key, result } = setup();
  await act(async () => {
    await result.current.mutateAsync({ threadId: "chat", archived: true });
  });
  expect(mocks.fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/chat"),
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ metadata: { deerflow_archived: true } }),
    }),
  );
  expect(client.getQueryData(key)).toEqual({
    ...original,
    metadata: { deerflow_pinned: true, deerflow_archived: true },
  });
  expect(
    client.getQueryData(["threads", "searchInfinite", { archived: false }]),
  ).toBeUndefined();
  client.clear();
});

test("failed archive keeps the visible thread and metadata unchanged", async () => {
  mocks.fetch.mockRejectedValue(new Error("Unavailable"));
  const { client, key, result } = setup();
  await act(async () => {
    await expect(
      result.current.mutateAsync({ threadId: "chat", archived: true }),
    ).rejects.toThrow("Unavailable");
  });
  expect(client.getQueryData(key)).toEqual(original);
  expect(
    client.getQueryData(["threads", "searchInfinite", { archived: false }]),
  ).toEqual({ pages: [[original]], pageParams: [0] });
  client.clear();
});

test("archive restarts an initial metadata read cancelled by the mutation", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let reads = 0;
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ metadata: { deerflow_archived: true } })),
  );
  const { result } = renderHook(
    () => ({
      metadata: useQuery({
        queryKey: ["thread", "metadata", "chat", false],
        queryFn: async () => {
          reads += 1;
          if (reads === 1) return new Promise<typeof original>(() => undefined);
          return {
            ...original,
            metadata: { ...original.metadata, deerflow_archived: true },
          };
        },
      }),
      mutation: useArchiveThread(),
    }),
    { wrapper },
  );
  await waitFor(() => expect(reads).toBe(1));
  await act(async () => {
    await result.current.mutation.mutateAsync({
      threadId: "chat",
      archived: true,
    });
  });
  await waitFor(() =>
    expect(result.current.metadata.data?.metadata).toEqual({
      deerflow_pinned: true,
      deerflow_archived: true,
    }),
  );
  client.clear();
});

test("a late pin response cannot roll back the confirmed archive flag", async () => {
  const { client, key, result: archive } = setup();
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result: pin } = renderHook(() => usePinThread(), { wrapper });
  let finishPin!: (value: Response) => void;
  mocks.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finishPin = resolve;
      }),
  );
  let pendingPin!: Promise<unknown>;
  act(() => {
    pendingPin = pin.current.mutateAsync({ threadId: "chat", pinned: true });
  });
  await waitFor(() => expect(finishPin).toBeDefined());
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ metadata: { deerflow_archived: true } })),
  );
  await act(async () => {
    await archive.current.mutateAsync({ threadId: "chat", archived: true });
  });
  await act(async () => {
    finishPin(
      new Response(
        JSON.stringify({
          metadata: { deerflow_pinned: true, deerflow_archived: false },
        }),
      ),
    );
    await pendingPin;
  });
  expect(client.getQueryData(key)).toEqual({
    ...original,
    metadata: { deerflow_pinned: true, deerflow_archived: true },
  });
  client.clear();
});
