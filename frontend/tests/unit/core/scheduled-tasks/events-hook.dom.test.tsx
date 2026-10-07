import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  fetchThreadTasks: rs.fn(),
  available: true,
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/features/hooks", () => ({
  useScheduledTasksFeature: () => ({
    available: mocks.available,
    running: true,
    toolEnabled: true,
    minIntervalSeconds: 60,
    isLoading: false,
  }),
}));
rs.mock("@/core/scheduled-tasks/api", () => ({
  fetchThreadScheduledTasks: mocks.fetchThreadTasks,
}));

import {
  scheduledTaskEventsQueryKey,
  useThreadScheduledTaskEvents,
  type ScheduledTaskEvent,
} from "@/core/scheduled-tasks/events";
import type { ThreadScheduledTask } from "@/core/scheduled-tasks/types";

const clients: QueryClient[] = [];

const EVENT = {
  id: "evt-1",
  task_id: "task-1",
  event: "task_stopped",
  reason_code: "agent_stop",
  task_title: "Daily digest",
  stop_condition: null,
  run_thread_id: "run-thread",
  run_number: 2,
  run_status: "success",
  max_runs: null,
  end_at: null,
  schedule_type: "cron",
  after_run_id: null,
  created_at: "2026-10-06T08:00:00Z",
} satisfies ScheduledTaskEvent;

function task(overrides: Partial<ThreadScheduledTask>): ThreadScheduledTask {
  return {
    id: "task-1",
    status: "enabled",
    last_run_at: null,
    active_run_status: null,
    thread_relation: "origin",
    ...overrides,
  } as ThreadScheduledTask;
}

function eventRequests() {
  return mocks.fetch.mock.calls.filter(([url]) =>
    String(url).includes("/scheduled-task-events"),
  );
}

function setup(
  threadId: string | null,
  options: { isNewThread?: boolean } = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () => useThreadScheduledTaskEvents(threadId, options),
    { wrapper },
  );
  return { client, hook };
}

beforeEach(() => {
  mocks.available = true;
  mocks.fetch
    .mockReset()
    .mockImplementation(async () => Response.json({ events: [EVENT] }));
  mocks.fetchThreadTasks.mockReset().mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

describe("useThreadScheduledTaskEvents", () => {
  test("a saved chat whose task was deleted still loads its event lines", async () => {
    const { hook } = setup("chat-1");
    await waitFor(() => expect(hook.result.current.data).toEqual([EVENT]));
    expect(eventRequests()).toHaveLength(1);
    // The route's maximum, so a busy chat does not lose its oldest lines.
    expect(String(eventRequests()[0]![0])).toBe(
      "/api/threads/chat-1/scheduled-task-events?limit=200",
    );
    // The chat's task list is empty (the task was deleted); the events
    // query does not depend on it.
    expect(mocks.fetchThreadTasks).toHaveBeenCalledWith("chat-1");
  });

  test("a new, unsaved chat makes no request", async () => {
    setup("chat-new", { isNewThread: true });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(eventRequests()).toHaveLength(0);
  });

  test("nothing is requested when scheduled tasks are unavailable", async () => {
    mocks.available = false;
    setup("chat-1");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(eventRequests()).toHaveLength(0);
    expect(mocks.fetchThreadTasks).not.toHaveBeenCalled();
  });

  test("refetches when a task of the chat changes state, not on the first list", async () => {
    mocks.fetchThreadTasks.mockResolvedValue([task({})]);
    const { client, hook } = setup("chat-1");
    await waitFor(() => expect(hook.result.current.data).toEqual([EVENT]));
    await waitFor(() =>
      expect(
        client.getQueryData(["scheduled-tasks", "thread", "chat-1"]),
      ).toBeTruthy(),
    );
    expect(eventRequests()).toHaveLength(1);

    // Same task list again: nothing changes.
    await act(async () => {
      await client.refetchQueries({
        queryKey: ["scheduled-tasks", "thread", "chat-1"],
      });
    });
    expect(eventRequests()).toHaveLength(1);

    mocks.fetchThreadTasks.mockResolvedValue([
      task({ status: "paused", last_run_at: "2026-10-06T08:00:00Z" }),
    ]);
    await act(async () => {
      await client.refetchQueries({
        queryKey: ["scheduled-tasks", "thread", "chat-1"],
      });
    });
    await waitFor(() => expect(eventRequests()).toHaveLength(2));
  });

  test("invalidating the scheduled-task prefix refetches the events", async () => {
    const { client, hook } = setup("chat-1");
    await waitFor(() => expect(hook.result.current.data).toEqual([EVENT]));
    expect(
      client.getQueryState(scheduledTaskEventsQueryKey("chat-1"))
        ?.dataUpdatedAt,
    ).toBeGreaterThan(0);
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["scheduled-tasks"] });
    });
    await waitFor(() => expect(eventRequests()).toHaveLength(2));
  });
});
