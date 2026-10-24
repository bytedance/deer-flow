import { afterEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import * as api from "@/core/background-tasks/api";
import {
  backgroundTaskQueryKey,
  backgroundTasksQueryKey,
  useBackgroundTask,
  useBackgroundTasks,
  useCancelBackgroundTask,
} from "@/core/background-tasks/hooks";
import type { BackgroundTaskDetail } from "@/core/background-tasks/types";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/background-tasks/api", () => ({
  fetchBackgroundTasks: rs.fn(),
  fetchBackgroundTask: rs.fn(),
  cancelBackgroundTask: rs.fn(),
}));

const fetchBackgroundTasks = rs.mocked(api.fetchBackgroundTasks);
const fetchBackgroundTask = rs.mocked(api.fetchBackgroundTask);
const cancelBackgroundTask = rs.mocked(api.cancelBackgroundTask);

function task(status: BackgroundTaskDetail["status"]): BackgroundTaskDetail {
  return {
    task_id: "task-1",
    task_name: "research",
    status,
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:05Z",
    error: null,
    tracking_degraded: false,
    cancel_requested: status === "cancelled",
    last_polled_at: null,
    last_poll_error: null,
    last_cancel_error: null,
    cancel_attempt_count: status === "cancelled" ? 1 : 0,
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

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

function makeClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return client;
}

test("a detail poll that started before the cancel cannot resurrect the task", async () => {
  const threadId = "thread-1";
  const active = task("working");
  const cancelled = task("cancelled");
  const staleRead = deferred<BackgroundTaskDetail>();

  const client = makeClient();
  client.setQueryData(backgroundTaskQueryKey(threadId, active.task_id), active);
  client.setQueryData(backgroundTasksQueryKey(threadId), [active]);

  // The expanded card polls every three seconds while the task is active. This
  // read was issued before the user pressed Cancel and is still in flight when
  // the server confirms the cancellation.
  const inFlight = client.fetchQuery({
    queryKey: backgroundTaskQueryKey(threadId, active.task_id),
    queryFn: () => staleRead.promise,
  });
  inFlight.catch(() => undefined);

  cancelBackgroundTask.mockResolvedValue(cancelled);
  fetchBackgroundTasks.mockResolvedValue([cancelled]);

  const { result } = renderHook(() => useCancelBackgroundTask(threadId), {
    wrapper: wrapperFor(client),
  });

  await act(async () => {
    await result.current.mutateAsync(active.task_id);
  });

  // The older read now answers with the pre-cancel state.
  staleRead.resolve(active);
  await act(async () => {
    await inFlight.catch(() => undefined);
  });

  await waitFor(() => {
    expect(
      client.getQueryData(backgroundTaskQueryKey(threadId, active.task_id)),
    ).toEqual(cancelled);
  });
  expect(client.getQueryData(backgroundTasksQueryKey(threadId))).toEqual([
    cancelled,
  ]);
});

test("a list poll that started before the cancel cannot resurrect the task", async () => {
  const threadId = "thread-1";
  const active = task("working");
  const cancelled = task("cancelled");
  const staleRead = deferred<BackgroundTaskDetail[]>();

  const client = makeClient();
  client.setQueryData(backgroundTaskQueryKey(threadId, active.task_id), active);
  client.setQueryData(backgroundTasksQueryKey(threadId), [active]);

  // The list polls on the same cadence; this read is older than the cancel.
  const inFlight = client.fetchQuery({
    queryKey: backgroundTasksQueryKey(threadId),
    queryFn: () => staleRead.promise,
  });
  inFlight.catch(() => undefined);

  cancelBackgroundTask.mockResolvedValue(cancelled);
  fetchBackgroundTasks.mockResolvedValue([cancelled]);

  const { result } = renderHook(() => useCancelBackgroundTask(threadId), {
    wrapper: wrapperFor(client),
  });

  await act(async () => {
    await result.current.mutateAsync(active.task_id);
  });

  staleRead.resolve([active]);
  await act(async () => {
    await inFlight.catch(() => undefined);
  });

  await waitFor(() => {
    expect(client.getQueryData(backgroundTasksQueryKey(threadId))).toEqual([
      cancelled,
    ]);
  });
  expect(
    client.getQueryData(backgroundTaskQueryKey(threadId, active.task_id)),
  ).toEqual(cancelled);
});

test("both polling queries pass TanStack's abort signal to the API", async () => {
  const threadId = "thread-1";
  const active = task("working");
  const client = makeClient();
  client.setQueryData(backgroundTasksQueryKey(threadId), [active]);
  client.setQueryData(backgroundTaskQueryKey(threadId, active.task_id), active);

  fetchBackgroundTasks.mockResolvedValue([active]);
  fetchBackgroundTask.mockResolvedValue(active);

  const list = renderHook(() => useBackgroundTasks(threadId), {
    wrapper: wrapperFor(client),
  });
  await waitFor(() => {
    expect(fetchBackgroundTasks).toHaveBeenCalledWith(threadId, {
      signal: expect.any(AbortSignal),
    });
  });
  list.unmount();

  const detail = renderHook(() => useBackgroundTask(threadId, active.task_id), {
    wrapper: wrapperFor(client),
  });
  await waitFor(() => {
    expect(fetchBackgroundTask).toHaveBeenCalledWith(threadId, active.task_id, {
      signal: expect.any(AbortSignal),
    });
  });
  detail.unmount();
});
