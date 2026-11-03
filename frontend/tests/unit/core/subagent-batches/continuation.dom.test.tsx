import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import {
  subagentBatchesKey,
  useSubagentBatches,
} from "@/core/subagent-batches/hooks";
import type { SubagentBatch } from "@/core/subagent-batches/types";
import { threadHistoryQueryKey } from "@/core/threads/hooks";
import { runInputsKey } from "@/core/threads/run-inputs";

const api = rs.hoisted(() => ({ batches: [] as SubagentBatch[] }));
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

test("a persisted follow-up refreshes the existing run and history observers once", async () => {
  api.batches = [];
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const invalidate = rs.spyOn(client, "invalidateQueries");
  const { result, rerender } = renderHook(
    () => useSubagentBatches("thread", { polling: false }),
    {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client }, children),
    },
  );
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
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
  await waitFor(() =>
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: runInputsKey("thread"),
    }),
  );
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: threadHistoryQueryKey("thread"),
  });
  const calls = invalidate.mock.calls.length;
  rerender();
  expect(invalidate.mock.calls).toHaveLength(calls);
});
