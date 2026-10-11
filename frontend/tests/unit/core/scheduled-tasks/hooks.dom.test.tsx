import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  type Query,
} from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/scheduled-tasks/api", () => ({
  fetchScheduledTask: rs.fn(),
}));

import { GatewayApiError, parseGatewayApiError } from "@/core/api/errors";
import { fetchScheduledTask } from "@/core/scheduled-tasks/api";
import { useScheduledTask } from "@/core/scheduled-tasks/hooks";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const fetchTask = rs.mocked(fetchScheduledTask);
const clients: QueryClient[] = [];

function setup() {
  // No default retry override: the hook's own retry policy is under test.
  const client = new QueryClient();
  clients.push(client);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

const TASK = {
  id: "task-1",
  status: "enabled",
  active_run_status: null,
} as unknown as ScheduledTask;

function refetchIntervalOf(client: QueryClient, id: string) {
  const query = client
    .getQueryCache()
    .find({ queryKey: ["scheduled-tasks", "task", id] });
  const option = (
    query?.options as
      | {
          refetchInterval?:
            | number
            | false
            | ((query: Query<ScheduledTask, Error, ScheduledTask>) => unknown);
        }
      | undefined
  )?.refetchInterval;
  return typeof option === "function"
    ? option(query as unknown as Query<ScheduledTask, Error, ScheduledTask>)
    : option;
}

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  fetchTask.mockReset();
});

describe("useScheduledTask", () => {
  it("treats a 404 as final: error with code task_not_found, no retry", async () => {
    fetchTask.mockRejectedValue(
      parseGatewayApiError(
        {
          detail: {
            code: "task_not_found",
            message: "Scheduled task not found",
          },
        },
        404,
        "fallback",
      ),
    );
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useScheduledTask("task-1"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(GatewayApiError);
    expect((result.current.error as GatewayApiError).code).toBe(
      "task_not_found",
    );
    expect(fetchTask).toHaveBeenCalledTimes(1);
    expect(refetchIntervalOf(client, "task-1")).toBe(false);
  });

  it("does not poll while the consumer is off screen", async () => {
    fetchTask.mockResolvedValue({
      ...TASK,
      active_run_status: "running",
    } as ScheduledTask);
    const { client, wrapper } = setup();
    const { result } = renderHook(
      () => useScheduledTask("task-1", { live: false }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(refetchIntervalOf(client, "task-1")).toBe(false);
  });

  it("polls fast while a run is active, and refetches when it comes into view", async () => {
    fetchTask.mockResolvedValue({
      ...TASK,
      active_run_status: "running",
    } as ScheduledTask);
    const { client, wrapper } = setup();
    const { result, rerender } = renderHook(
      ({ live }) => useScheduledTask("task-1", { live, initialData: TASK }),
      { wrapper, initialProps: { live: false } },
    );
    await waitFor(() => expect(fetchTask).toHaveBeenCalledTimes(1));
    rerender({ live: true });
    await waitFor(() => expect(fetchTask).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(result.current.data?.active_run_status).toBe("running"),
    );
    expect(refetchIntervalOf(client, "task-1")).toBe(3000);
  });

  it("shares one request between consumers of the same task", async () => {
    fetchTask.mockResolvedValue(TASK);
    const { wrapper } = setup();
    const { result } = renderHook(
      () => [useScheduledTask("task-1"), useScheduledTask("task-1")] as const,
      { wrapper },
    );
    await waitFor(() => expect(result.current[1].isSuccess).toBe(true));
    expect(fetchTask).toHaveBeenCalledTimes(1);
  });
});
