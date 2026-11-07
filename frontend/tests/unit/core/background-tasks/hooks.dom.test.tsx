import { afterEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";

import * as api from "@/core/background-tasks/api";
import {
  backgroundTaskQueryKey,
  backgroundTasksQueryKey,
  useCancelBackgroundTask,
} from "@/core/background-tasks/hooks";
import type {
  BackgroundTask,
  BackgroundTaskDetail,
  BackgroundTaskStatus,
} from "@/core/background-tasks/types";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/background-tasks/api", () => ({
  fetchBackgroundTasks: rs.fn(),
  fetchBackgroundTask: rs.fn(),
  cancelBackgroundTask: rs.fn(),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

const THREAD_ID = "thread-1";
const TASK_ID = "task-1";

function task(status: BackgroundTaskStatus): BackgroundTask {
  return {
    task_id: TASK_ID,
    task_name: "MCP task",
    status,
    created_at: "2026-10-20T07:00:00Z",
    updated_at: "2026-10-20T07:00:03Z",
    error: null,
    tracking_degraded: false,
    cancel_requested: status === "cancelled",
  };
}

function detail(status: BackgroundTaskStatus): BackgroundTaskDetail {
  return {
    ...task(status),
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
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  rs.resetAllMocks();
});

function makeClient(seed: BackgroundTaskDetail): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  clients.push(client);
  client.setQueryData(backgroundTasksQueryKey(THREAD_ID), [task(seed.status)]);
  client.setQueryData(backgroundTaskQueryKey(THREAD_ID, TASK_ID), seed);
  return client;
}

function wrapperFor(client: QueryClient) {
  return function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

test("a detail or list poll that started before the cancel cannot undo it", async () => {
  const working = detail("working");
  const cancelled = detail("cancelled");
  const staleDetail = deferred<BackgroundTaskDetail>();
  const staleList = deferred<BackgroundTask[]>();
  rs.mocked(api.fetchBackgroundTask).mockReturnValue(staleDetail.promise);
  rs.mocked(api.fetchBackgroundTasks).mockReturnValue(staleList.promise);
  rs.mocked(api.cancelBackgroundTask).mockResolvedValue(cancelled);

  const client = makeClient(working);
  const { result } = renderHook(() => useCancelBackgroundTask(THREAD_ID), {
    wrapper: wrapperFor(client),
  });

  // Both the expanded card's detail poll and the list poll were in flight when
  // the user pressed Cancel, so both still carry the pre-cancel snapshot.
  let detailRead!: Promise<BackgroundTaskDetail>;
  let listRead!: Promise<BackgroundTask[]>;
  act(() => {
    detailRead = client.fetchQuery({
      queryKey: backgroundTaskQueryKey(THREAD_ID, TASK_ID),
      queryFn: () => api.fetchBackgroundTask(THREAD_ID, TASK_ID),
    });
    listRead = client.fetchQuery({
      queryKey: backgroundTasksQueryKey(THREAD_ID),
      queryFn: () => api.fetchBackgroundTasks(THREAD_ID),
    });
  });
  expect(api.fetchBackgroundTask).toHaveBeenCalledTimes(1);
  expect(api.fetchBackgroundTasks).toHaveBeenCalledTimes(1);

  await act(async () => {
    await result.current.mutateAsync(TASK_ID);
  });
  const detailKey = backgroundTaskQueryKey(THREAD_ID, TASK_ID);
  const listKey = backgroundTasksQueryKey(THREAD_ID);
  expect(client.getQueryData<BackgroundTaskDetail>(detailKey)?.status).toBe(
    "cancelled",
  );
  expect(client.getQueryData<BackgroundTask[]>(listKey)?.[0]?.status).toBe(
    "cancelled",
  );

  await act(async () => {
    staleDetail.resolve(working);
    staleList.resolve([task("working")]);
    await Promise.allSettled([detailRead, listRead]);
  });

  // The confirmed cancellation survives the reads that resolved after it, so
  // the card does not fall back to "working" and resume polling.
  expect(client.getQueryData<BackgroundTaskDetail>(detailKey)?.status).toBe(
    "cancelled",
  );
  expect(client.getQueryData<BackgroundTask[]>(listKey)?.[0]?.status).toBe(
    "cancelled",
  );
});

test("a failed cancel keeps the cache and lets the in-flight read finish", async () => {
  const working = detail("working");
  const refreshed = detail("working");
  refreshed.last_polled_at = "2026-10-20T07:00:06Z";
  const staleDetail = deferred<BackgroundTaskDetail>();
  rs.mocked(api.fetchBackgroundTask).mockReturnValue(staleDetail.promise);
  rs.mocked(api.cancelBackgroundTask).mockRejectedValue(
    new Error("Cancel failed"),
  );

  const client = makeClient(working);
  const { result } = renderHook(() => useCancelBackgroundTask(THREAD_ID), {
    wrapper: wrapperFor(client),
  });

  let detailRead!: Promise<BackgroundTaskDetail>;
  act(() => {
    detailRead = client.fetchQuery({
      queryKey: backgroundTaskQueryKey(THREAD_ID, TASK_ID),
      queryFn: () => api.fetchBackgroundTask(THREAD_ID, TASK_ID),
    });
  });

  await act(async () => {
    await expect(result.current.mutateAsync(TASK_ID)).rejects.toThrow(
      "Cancel failed",
    );
  });
  expect(
    client.getQueryData<BackgroundTaskDetail>(
      backgroundTaskQueryKey(THREAD_ID, TASK_ID),
    ),
  ).toEqual(working);

  await act(async () => {
    staleDetail.resolve(refreshed);
    await detailRead;
  });
  expect(
    client.getQueryData<BackgroundTaskDetail>(
      backgroundTaskQueryKey(THREAD_ID, TASK_ID),
    )?.last_polled_at,
  ).toBe("2026-10-20T07:00:06Z");
});
