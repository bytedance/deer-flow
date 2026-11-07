import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { fetch } from "@/core/api/fetcher";
import {
  backgroundTaskQueryKey,
  backgroundTasksQueryKey,
  useBackgroundTask,
  useBackgroundTasks,
  useCancelBackgroundTask,
} from "@/core/background-tasks/hooks";
import type { BackgroundTaskDetail } from "@/core/background-tasks/types";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: { backgroundTasks: { cancelFailed: "Cancel failed" } },
  }),
}));
rs.mock("sonner", () => ({ toast: { error: rs.fn() } }));

const working: BackgroundTaskDetail = {
  task_id: "task-1",
  task_name: "Generate report",
  status: "working",
  created_at: "2026-08-08T00:00:00Z",
  updated_at: "2026-08-08T00:00:01Z",
  error: null,
  tracking_degraded: false,
  cancel_requested: false,
  last_polled_at: null,
  last_poll_error: null,
  last_cancel_error: null,
  cancel_attempt_count: 0,
  notification_status: "none",
  notification_error: null,
  notification_attempt_count: 0,
  result: null,
  result_preview: null,
  result_truncated: false,
  result_artifact: null,
  input_required: null,
};
const cancelled: BackgroundTaskDetail = {
  ...working,
  status: "cancelled",
  cancel_requested: true,
};

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const clients: QueryClient[] = [];
function setupClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  clients.push(client);
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }
  return { client, wrapper };
}

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  rs.resetAllMocks();
});

for (const { scope, cached } of [
  { scope: "detail", cached: true },
  { scope: "detail", cached: false },
  { scope: "list", cached: true },
  { scope: "list", cached: false },
] as const) {
  test(`a delayed ${cached ? "cached" : "initial"} ${scope} read cannot undo cancellation after the panel closes`, async () => {
    const delayed = deferred<Response>();
    const before = scope === "detail" ? working : [working];
    const confirmed = scope === "detail" ? cancelled : [cancelled];
    // An unloaded list is populated only by a fresh list GET.
    const expectedAfterCancel =
      scope === "list" && !cached ? undefined : confirmed;
    rs.mocked(fetch).mockImplementation((_url, init) =>
      init?.method === "POST"
        ? Promise.resolve(jsonResponse(cancelled))
        : delayed.promise,
    );
    const { client, wrapper } = setupClient();
    const key =
      scope === "detail"
        ? backgroundTaskQueryKey("thread-1", working.task_id)
        : backgroundTasksQueryKey("thread-1");
    if (cached) client.setQueryData(key, before);
    const { result, rerender } = renderHook(
      ({ enabled }) => ({
        detail: useBackgroundTask("thread-1", working.task_id, {
          enabled: enabled && scope === "detail",
        }),
        list: useBackgroundTasks("thread-1", {
          enabled: enabled && scope === "list",
        }),
        cancel: useCancelBackgroundTask("thread-1"),
      }),
      { initialProps: { enabled: true }, wrapper },
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    // The cancel request can finish after the user closes the panel. Disabled
    // queries are not refetched by invalidation, so it cannot fence this GET.
    rerender({ enabled: false });
    await act(async () => {
      await result.current.cancel.mutateAsync(working.task_id);
    });
    expect(client.getQueryData(key)).toEqual(expectedAfterCancel);

    await act(async () => {
      // Deliberately ignore transport abort to verify the cache fence as well.
      delayed.resolve(jsonResponse(before));
      await delayed.promise;
    });
    expect(client.getQueryData(key)).toEqual(expectedAfterCancel);

    // A later legitimate refresh still updates the cache.
    rs.mocked(fetch).mockResolvedValue(jsonResponse(confirmed));
    rerender({ enabled: true });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(client.getQueryState(key)?.fetchStatus).toBe("idle"),
    );
    expect(client.getQueryData(key)).toEqual(confirmed);
  });
}

test("cancellation aborts both HTTP reads and preserves sibling tasks and other threads", async () => {
  const delayedReads: {
    url: string;
    signal: AbortSignal | null | undefined;
    resolve: (value: Response) => void;
  }[] = [];
  rs.mocked(fetch).mockImplementation((url, init) => {
    if (init?.method === "POST")
      return Promise.resolve(jsonResponse(cancelled));
    const read = deferred<Response>();
    delayedReads.push({
      url: typeof url === "string" ? url : url.url,
      signal: init?.signal,
      resolve: read.resolve,
    });
    return read.promise;
  });
  const { client, wrapper } = setupClient();
  const otherKey = backgroundTaskQueryKey("other-thread", working.task_id);
  client.setQueryData(otherKey, working);
  const { result } = renderHook(
    () => ({
      detail: useBackgroundTask("thread-1", working.task_id),
      list: useBackgroundTasks("thread-1"),
      other: useBackgroundTask("other-thread", working.task_id),
      sibling: useBackgroundTask("thread-1", "task-2"),
      cancel: useCancelBackgroundTask("thread-1"),
    }),
    { wrapper },
  );
  await waitFor(() => expect(delayedReads).toHaveLength(4));
  expect(delayedReads.every((read) => read.signal instanceof AbortSignal)).toBe(
    true,
  );
  await act(async () => {
    await result.current.cancel.mutateAsync(working.task_id);
  });
  expect(delayedReads[0]!.signal!.aborted).toBe(true);
  expect(delayedReads[1]!.signal!.aborted).toBe(true);
  expect(delayedReads[2]!.signal!.aborted).toBe(false);
  expect(delayedReads[3]!.signal!.aborted).toBe(false);
  // Only the list starts a replacement GET. The confirmed detail is already
  // authoritative, and unrelated initial detail loads must remain in flight.
  expect(delayedReads).toHaveLength(5);
  expect(client.getQueryData(otherKey)).toEqual(working);
  expect(
    client.getQueryData(backgroundTaskQueryKey("thread-1", working.task_id)),
  ).toEqual(cancelled);
  await act(async () => {
    for (const read of delayedReads) {
      const value = read.url.includes("?limit=") ? [cancelled] : working;
      read.resolve(jsonResponse(value));
    }
  });
  expect(
    client.getQueryData(backgroundTaskQueryKey("thread-1", working.task_id)),
  ).toEqual(cancelled);
  await waitFor(() => expect(result.current.sibling.data).toEqual(working));
});

test("failed cancellation allows a pending detail refresh to finish", async () => {
  const delayed = deferred<Response>();
  rs.mocked(fetch).mockImplementation((_url, init) =>
    init?.method === "POST"
      ? Promise.resolve(jsonResponse({ detail: "Unavailable" }, 503))
      : delayed.promise,
  );
  const { client, wrapper } = setupClient();
  const key = backgroundTaskQueryKey("thread-1", working.task_id);
  client.setQueryData(key, working);
  const { result } = renderHook(
    () => ({
      detail: useBackgroundTask("thread-1", working.task_id),
      cancel: useCancelBackgroundTask("thread-1"),
    }),
    { wrapper },
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await act(async () => {
    await expect(
      result.current.cancel.mutateAsync(working.task_id),
    ).rejects.toThrow("Unavailable");
  });
  expect(client.getQueryData(key)).toEqual(working);
  const completed = { ...working, status: "completed" };
  await act(async () => {
    delayed.resolve(jsonResponse(completed));
  });
  await waitFor(() => expect(result.current.detail.data).toEqual(completed));
});
