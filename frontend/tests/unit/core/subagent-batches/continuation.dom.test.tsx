import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import {
  subagentBatchesKey,
  useSubagentBatches,
} from "@/core/subagent-batches/hooks";
import type { SubagentBatch } from "@/core/subagent-batches/types";
import { threadHistoryQueryKey, useThreadRuns } from "@/core/threads/hooks";
import { runInputsKey } from "@/core/threads/run-inputs";

const api = rs.hoisted(() => ({
  batches: [] as SubagentBatch[],
  runs: [] as Array<{ run_id: string; status: string }>,
}));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({ runs: { list: async () => api.runs } }),
}));
rs.mock("@/core/subagent-batches/api", () => ({
  fetchSubagentBatches: async () => api.batches,
  controlSubagentBatch: rs.fn(),
  fetchSubagentBatchItemDetail: rs.fn(),
  fetchSubagentBatchItems: rs.fn(),
  retrySubagentBatchItem: rs.fn(),
}));
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
});

test("a newly admitted follow-up is discovered before Run inputs open", async () => {
  api.batches = [];
  api.runs = [];
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  client.setQueryData(runInputsKey("thread"), {
    items: [],
    active_run_id: null,
  });
  const invalidate = rs.spyOn(client, "invalidateQueries");
  const { result, rerender } = renderHook(
    () => ({
      batches: useSubagentBatches("thread", { polling: false }),
      runs: useThreadRuns("thread"),
    }),
    {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client }, children),
    },
  );
  await waitFor(() => expect(result.current.runs.data).toEqual([]));
  await waitFor(() => expect(result.current.batches.isSuccess).toBe(true));
  api.runs = [{ run_id: "follow-up", status: "pending" }];
  api.batches = [
    {
      id: "batch",
      status: "completed",
      continuation_status: "dispatched",
      continuation_run_id: "follow-up",
    } as SubagentBatch,
  ];
  await act(async () => {
    await client.invalidateQueries({ queryKey: subagentBatchesKey("thread") });
  });
  await waitFor(() => expect(result.current.runs.data).toEqual(api.runs));
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: threadHistoryQueryKey("thread"),
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: runInputsKey("thread") });
  const calls = invalidate.mock.calls.length;
  rerender();
  expect(invalidate.mock.calls).toHaveLength(calls);
  expect(client.getQueryData(runInputsKey("thread"))).toEqual({
    items: [],
    active_run_id: null,
  });
});
