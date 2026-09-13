import { afterEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/scheduled-tasks/api", () => ({
  fetchScheduledTaskRuns: rs.fn(),
}));

import { fetchScheduledTaskRuns } from "@/core/scheduled-tasks/api";
import { useScheduledTaskRunHistory } from "@/core/scheduled-tasks/run-history";
import type { ScheduledTaskRun } from "@/core/scheduled-tasks/types";

const fetchRuns = rs.mocked(fetchScheduledTaskRuns);
const clients: QueryClient[] = [];
function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}
const rows = (count: number, prefix = "run") =>
  Array.from(
    { length: count },
    (_, index) => ({ id: `${prefix}-${index}` }) as ScheduledTaskRun,
  );
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  fetchRuns.mockReset();
});

test("a full final page does not expose the next-page sentinel", async () => {
  fetchRuns.mockImplementation(async (_task, page) =>
    rows(page?.offset === 0 ? 51 : 50),
  );
  const { result } = renderHook(() => useScheduledTaskRunHistory("task-a"), {
    wrapper: wrapper(),
  });
  await waitFor(() => expect(result.current.hasOlder).toBe(true));
  expect(result.current.data).toHaveLength(50);
  act(() => result.current.older());
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.hasOlder).toBe(false);
  expect(result.current.data).toHaveLength(50);
  expect(fetchRuns).toHaveBeenLastCalledWith("task-a", {
    limit: 51,
    offset: 50,
    signal: expect.any(AbortSignal),
  });
});

test("switching tasks aborts an in-flight older page and rejects its late result", async () => {
  let oldSignal: AbortSignal | undefined;
  let finishOld!: (data: ScheduledTaskRun[]) => void;
  fetchRuns.mockImplementation(async (id, page) => {
    if (id === "task-a" && page?.offset === 50) {
      oldSignal = page.signal;
      return new Promise((resolve) => {
        finishOld = resolve;
      });
    }
    return rows(id === "task-a" ? 51 : 1, id);
  });
  const { result, rerender } = renderHook(
    ({ taskId }) => useScheduledTaskRunHistory(taskId),
    { initialProps: { taskId: "task-a" }, wrapper: wrapper() },
  );
  await waitFor(() => expect(result.current.hasOlder).toBe(true));
  act(() => result.current.older());
  await waitFor(() => expect(oldSignal).toBeDefined());
  expect(result.current.isPending).toBe(true);
  rerender({ taskId: "task-b" });
  await waitFor(() => expect(result.current.data?.[0]?.id).toBe("task-b-0"));
  expect(result.current.page).toBe(0);
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => finishOld(rows(50, "stale-task-a")));
  expect(result.current.data?.[0]?.id).toBe("task-b-0");
});

test("an empty older page retains a route back to the latest records", async () => {
  fetchRuns.mockImplementation(async (_id, page) =>
    rows(page?.offset === 0 ? 51 : 0),
  );
  const { result } = renderHook(() => useScheduledTaskRunHistory("task-a"), {
    wrapper: wrapper(),
  });
  await waitFor(() => expect(result.current.hasOlder).toBe(true));
  act(() => result.current.older());
  await waitFor(() => expect(result.current.data).toEqual([]));
  expect(result.current.page).toBe(1);
  fetchRuns.mockImplementation(async () => rows(1, "new"));
  act(() => result.current.latest());
  await waitFor(() => expect(result.current.data?.[0]?.id).toBe("new-0"));
  expect(result.current.page).toBe(0);
});
