import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/background-tasks/api", () => ({
  cancelBackgroundTask: rs.fn(),
  fetchBackgroundTask: rs.fn(),
  fetchBackgroundTasks: rs.fn(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: { backgroundTasks: { cancelFailed: "Failed to cancel task" } },
  }),
}));

import {
  cancelBackgroundTask,
  fetchBackgroundTask,
} from "@/core/background-tasks/api";
import {
  backgroundTaskQueryKey,
  useBackgroundTask,
  useCancelBackgroundTask,
} from "@/core/background-tasks/hooks";
import type { BackgroundTaskDetail } from "@/core/background-tasks/types";

const workingTask: BackgroundTaskDetail = {
  task_id: "task-1",
  task_name: "Generate report",
  status: "working",
  created_at: "2026-10-20T00:00:00Z",
  updated_at: "2026-10-20T00:00:01Z",
  error: null,
  tracking_degraded: false,
  cancel_requested: false,
  last_polled_at: "2026-10-20T00:00:01Z",
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  rs.resetAllMocks();
});

test("a delayed detail poll cannot undo a confirmed cancellation", async () => {
  const stalePoll = deferred<BackgroundTaskDetail>();
  const cancelledTask: BackgroundTaskDetail = {
    ...workingTask,
    status: "cancelled",
    cancel_requested: true,
    updated_at: "2026-10-20T00:00:02Z",
  };
  rs.mocked(fetchBackgroundTask).mockReturnValue(stalePoll.promise);
  rs.mocked(cancelBackgroundTask).mockResolvedValue(cancelledTask);

  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  const detailKey = backgroundTaskQueryKey("thread-1", "task-1");
  client.setQueryData(detailKey, workingTask);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result, unmount } = renderHook(
    () => ({
      detail: useBackgroundTask("thread-1", "task-1"),
      cancel: useCancelBackgroundTask("thread-1"),
    }),
    { wrapper },
  );

  try {
    await waitFor(() => expect(fetchBackgroundTask).toHaveBeenCalledTimes(1));
    await act(async () => {
      await result.current.cancel.mutateAsync("task-1");
    });
    expect(client.getQueryData(detailKey)).toEqual(cancelledTask);

    await act(async () => {
      stalePoll.resolve(workingTask);
      await stalePoll.promise;
    });
    await waitFor(() => expect(result.current.detail.isFetching).toBe(false));

    expect(result.current.detail.data).toEqual(cancelledTask);
    expect(client.getQueryData(detailKey)).toEqual(cancelledTask);
    expect(fetchBackgroundTask).toHaveBeenCalledTimes(1);
  } finally {
    unmount();
    client.clear();
  }
});
