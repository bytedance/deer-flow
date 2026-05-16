import { expect, test } from "vitest";

import { threadTokenUsageToTokenUsage } from "@/core/threads/token-usage";
import type { ThreadTokenUsageResponse } from "@/core/threads/types";

test("maps backend thread token usage to UI token usage", () => {
  const response: ThreadTokenUsageResponse = {
    thread_id: "thread-1",
    total_input_tokens: 90,
    total_output_tokens: 60,
    total_tokens: 150,
    total_runs: 2,
    by_model: { unknown: { tokens: 150, runs: 2 } },
    by_caller: {
      lead_agent: 120,
      subagent: 25,
      middleware: 5,
    },
  };

  expect(threadTokenUsageToTokenUsage(response)).toEqual({
    inputTokens: 90,
    outputTokens: 60,
    totalTokens: 150,
  });
});

test("returns null when backend thread token usage is unavailable", () => {
  expect(threadTokenUsageToTokenUsage(null)).toBeNull();
  expect(threadTokenUsageToTokenUsage(undefined)).toBeNull();
});
