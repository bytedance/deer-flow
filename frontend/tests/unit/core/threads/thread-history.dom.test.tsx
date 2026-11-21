import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({ fetch: rs.fn(), toastError: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("sonner", () => ({ toast: { error: mocks.toastError } }));

import { useThreadHistory } from "@/core/threads/hooks";
import type { RunMessage } from "@/core/threads/types";

type PendingRequest = {
  url: URL;
  signal: AbortSignal | null | undefined;
  resolve: (response: Response) => void;
};

let requests: PendingRequest[];
let queryClient: QueryClient;

function row(seq: number, text: string): RunMessage {
  return {
    run_id: "run-1",
    seq,
    content: { id: `message-${seq}`, type: "human", content: text },
    metadata: { caller: "" },
    created_at: "2026-01-01T00:00:00Z",
  };
}

function page(data: RunMessage[], nextBeforeSeq: number | null = null) {
  return Response.json({
    data,
    has_more: nextBeforeSeq !== null,
    next_before_seq: nextBeforeSeq,
  });
}

function mount(threadId = "thread-a") {
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(({ id }) => useThreadHistory(id), {
    initialProps: { id: threadId },
    wrapper,
  });
}

beforeEach(() => {
  requests = [];
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  mocks.toastError.mockReset();
  mocks.fetch.mockReset();
  mocks.fetch.mockImplementation(
    (url: string, init?: RequestInit) =>
      new Promise<Response>((resolve) => {
        // Keep the response controllable even after abort: a late response must
        // not replace the history of the conversation now on screen.
        requests.push({
          url: new URL(url, "http://localhost"),
          signal: init?.signal,
          resolve,
        });
      }),
  );
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  rs.restoreAllMocks();
});

test("switching chats cancels an older-page read and isolates the new history", async () => {
  const { result, rerender } = mount();
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => requests[0]!.resolve(page([row(3, "Chat A")], 3)));
  await waitFor(() => expect(result.current.messages).toHaveLength(1));

  act(() => {
    void result.current.loadMore();
  });
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1]!.url.searchParams.get("before_seq")).toBe("3");
  expect(requests[1]!.signal?.aborted).toBe(false);

  rerender({ id: "thread-b" });
  await waitFor(() => expect(requests).toHaveLength(3));
  expect(requests[1]!.signal?.aborted).toBe(true);
  expect(requests[2]!.url.pathname).toBe("/api/threads/thread-b/messages/page");
  expect(result.current.messages).toEqual([]);

  await act(async () => requests[2]!.resolve(page([row(1, "Chat B")])));
  await waitFor(() =>
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "Chat B",
    ]),
  );
  await act(async () => requests[1]!.resolve(page([row(1, "Older chat A")])));
  expect(result.current.messages.map((message) => message.content)).toEqual([
    "Chat B",
  ]);
  expect(mocks.toastError).not.toHaveBeenCalled();
});

test("unmounting cancels the initial read and reopening starts a fresh one", async () => {
  const first = mount();
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0]!.signal?.aborted).toBe(false);
  first.unmount();
  expect(requests[0]!.signal?.aborted).toBe(true);

  const { result } = mount();
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1]!.signal?.aborted).toBe(false);
  await act(async () => requests[0]!.resolve(page([row(1, "Stale history")])));
  expect(result.current.messages).toEqual([]);

  await act(async () => requests[1]!.resolve(page([row(1, "Fresh history")])));
  await waitFor(() =>
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "Fresh history",
    ]),
  );
  expect(mocks.toastError).not.toHaveBeenCalled();
});

test("a failed older-page read preserves messages and retries the same cursor", async () => {
  rs.spyOn(console, "error").mockImplementation(() => undefined);
  const { result } = mount();
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => requests[0]!.resolve(page([row(3, "Recent")], 3)));
  await waitFor(() => expect(result.current.hasMore).toBe(true));

  let pending: ReturnType<typeof result.current.loadMore>;
  act(() => {
    pending = result.current.loadMore();
  });
  await waitFor(() => expect(requests).toHaveLength(2));
  await act(async () => {
    requests[1]!.resolve(
      Response.json({ detail: "Temporarily unavailable" }, { status: 503 }),
    );
    await pending;
  });
  await waitFor(() => expect(mocks.toastError).toHaveBeenCalledTimes(1));
  expect(result.current.messages.map((message) => message.content)).toEqual([
    "Recent",
  ]);
  expect(result.current.loading).toBe(false);
  expect(result.current.hasMore).toBe(true);

  act(() => {
    pending = result.current.loadMore();
  });
  await waitFor(() => expect(requests).toHaveLength(3));
  expect(requests[2]!.url.href).toBe(requests[1]!.url.href);
  expect(requests[2]!.url.searchParams.get("before_seq")).toBe("3");
  await act(async () => {
    requests[2]!.resolve(page([row(1, "First"), row(2, "Second")]));
    await pending;
  });
  await waitFor(() => expect(result.current.hasMore).toBe(false));
  expect(result.current.messages.map((message) => message.content)).toEqual([
    "First",
    "Second",
    "Recent",
  ]);
});
