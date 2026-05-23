import { expect, test } from "vitest";

import {
  selectContextUsage,
  threadTokenUsageToTokenUsage,
} from "@/core/threads/token-usage";
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

const _baseResponse = {
  thread_id: "thread-1",
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_tokens: 0,
  total_runs: 0,
  by_model: {},
  by_caller: { lead_agent: 0, subagent: 0, middleware: 0 },
} satisfies ThreadTokenUsageResponse;

test("selectContextUsage projects the backend block to UI shape", () => {
  const response: ThreadTokenUsageResponse = {
    ..._baseResponse,
    context_usage: {
      token_count: 350,
      max_context_tokens: 1000,
      percentage: 35,
    },
  };

  expect(selectContextUsage(response)).toEqual({
    tokenCount: 350,
    maxContextTokens: 1000,
    percentage: 35,
  });
});

test("selectContextUsage preserves nullable capacity and percentage", () => {
  const response: ThreadTokenUsageResponse = {
    ..._baseResponse,
    context_usage: {
      token_count: 200,
      max_context_tokens: null,
      percentage: null,
    },
  };

  expect(selectContextUsage(response)).toEqual({
    tokenCount: 200,
    maxContextTokens: null,
    percentage: null,
  });
});

test("selectContextUsage returns null when context_usage is missing", () => {
  expect(selectContextUsage(_baseResponse)).toBeNull();
  expect(
    selectContextUsage({ ..._baseResponse, context_usage: null }),
  ).toBeNull();
  expect(selectContextUsage(null)).toBeNull();
  expect(selectContextUsage(undefined)).toBeNull();
});
