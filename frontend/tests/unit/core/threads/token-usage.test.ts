import { expect, test } from "@rstest/core";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

import {
  contextUsageCategories,
  contextUsageDenominator,
  contextUsageShare,
  retainThreadTokenUsagePlaceholder,
  selectContextUsage,
  selectContextUsageBreakdown,
  threadTokenUsageQueryKey,
  threadTokenUsageToTokenUsage,
  withContextUsageWindow,
  type ContextUsageBreakdown,
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

test("retains placeholder usage only for the current thread", () => {
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

  expect(retainThreadTokenUsagePlaceholder(response, "thread-1")).toBe(
    response,
  );
  expect(
    retainThreadTokenUsagePlaceholder(response, "thread-2"),
  ).toBeUndefined();
  expect(retainThreadTokenUsagePlaceholder(null, undefined)).toBeUndefined();
});

test("query observer keeps same-thread data but drops it while a new thread is pending", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const threadA: ThreadTokenUsageResponse = {
    thread_id: "thread-a",
    total_input_tokens: 90,
    total_output_tokens: 60,
    total_tokens: 150,
    total_runs: 2,
    by_model: { unknown: { tokens: 150, runs: 2 } },
    by_caller: { lead_agent: 120, subagent: 25, middleware: 5 },
  };
  const threadB: ThreadTokenUsageResponse = {
    ...threadA,
    thread_id: "thread-b",
    total_tokens: 200,
  };
  let queryResult = Promise.resolve(threadA);
  let resolveRefresh: (value: ThreadTokenUsageResponse) => void = () =>
    undefined;
  let resolveThreadB: (value: ThreadTokenUsageResponse) => void = () =>
    undefined;
  const observer = new QueryObserver<ThreadTokenUsageResponse | null>(
    queryClient,
    {
      queryKey: threadTokenUsageQueryKey("thread-a"),
      queryFn: () => queryResult,
      placeholderData: (previous) =>
        retainThreadTokenUsagePlaceholder(previous, "thread-a"),
    },
  );
  const unsubscribe = observer.subscribe(() => undefined);

  try {
    await observer.refetch();
    expect(observer.getCurrentResult().data).toBe(threadA);

    queryResult = new Promise((resolve) => {
      resolveRefresh = resolve;
    });
    const sameThreadRefetch = observer.refetch();
    expect(observer.getCurrentResult().data).toBe(threadA);
    resolveRefresh(threadA);
    await sameThreadRefetch;

    const pendingThreadB = new Promise<ThreadTokenUsageResponse>((resolve) => {
      resolveThreadB = resolve;
    });
    observer.setOptions({
      queryKey: threadTokenUsageQueryKey("thread-b"),
      queryFn: () => pendingThreadB,
      retry: false,
      placeholderData: (previous) =>
        retainThreadTokenUsagePlaceholder(previous, "thread-b"),
    });
    expect(observer.getCurrentResult().data).toBeUndefined();
    expect(observer.getCurrentResult().isPlaceholderData).toBe(false);

    resolveThreadB(threadB);
    await observer.refetch();
    expect(observer.getCurrentResult().data).toBe(threadB);
  } finally {
    resolveRefresh(threadA);
    resolveThreadB(threadB);
    unsubscribe();
    queryClient.clear();
  }
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

const _breakdownPayload: NonNullable<
  NonNullable<ThreadTokenUsageResponse["context_usage"]>["breakdown"]
> = {
  total_tokens: 1000,
  percentage: 10,
  remaining_tokens: 9000,
  system_prompt_tokens: 100,
  builtin_tools_tokens: 200,
  mcp_tools_tokens: 50,
  skill_body_tokens: 25,
  memory_tokens: 30,
  task_state_tokens: 40,
  other_injection_tokens: 5,
  conversation_tokens: 500,
  tool_result_tokens: 50,
  model_name: "offline",
  context_window: 10000,
  captured_at: "2026-11-12T00:00:00Z",
};

const _breakdown: ContextUsageBreakdown = {
  totalTokens: 1000,
  percentage: 10,
  remainingTokens: 9000,
  systemPromptTokens: 100,
  builtinToolsTokens: 200,
  mcpToolsTokens: 50,
  skillBodyTokens: 25,
  memoryTokens: 30,
  taskStateTokens: 40,
  otherInjectionTokens: 5,
  conversationTokens: 500,
  toolResultTokens: 50,
  modelName: "offline",
  contextWindow: 10000,
  capturedAt: "2026-11-12T00:00:00Z",
};

test("selectContextUsageBreakdown projects the backend snapshot to UI shape", () => {
  const response: ThreadTokenUsageResponse = {
    ..._baseResponse,
    context_usage: {
      token_count: 1000,
      max_context_tokens: 10000,
      percentage: 10,
      breakdown: _breakdownPayload,
    },
  };

  expect(selectContextUsageBreakdown(response)).toEqual(_breakdown);
});

test("selectContextUsageBreakdown returns null without a snapshot", () => {
  expect(selectContextUsageBreakdown(_baseResponse)).toBeNull();
  expect(
    selectContextUsageBreakdown({
      ..._baseResponse,
      context_usage: {
        token_count: 1,
        max_context_tokens: null,
        percentage: null,
        breakdown: null,
      },
    }),
  ).toBeNull();
  expect(selectContextUsageBreakdown(null)).toBeNull();
  expect(selectContextUsageBreakdown(undefined)).toBeNull();
});

test("contextUsageCategories groups the flat counts exhaustively", () => {
  const categories = contextUsageCategories(_breakdown);
  expect(categories.map((category) => [category.key, category.tokens])).toEqual(
    [
      ["systemPrompt", 100],
      ["tools", 250],
      ["skills", 25],
      ["memoryContext", 75],
      ["conversation", 550],
    ],
  );
  expect(
    categories.reduce((total, category) => total + category.tokens, 0),
  ).toBe(_breakdown.totalTokens);
  expect(categories[1]?.subcategories).toEqual([
    { key: "builtinTools", tokens: 200 },
    { key: "mcpTools", tokens: 50 },
  ]);
  expect(categories[3]?.subcategories).toEqual([
    { key: "memory", tokens: 30 },
    { key: "taskState", tokens: 40 },
    { key: "otherInjection", tokens: 5 },
  ]);
  expect(categories[4]?.subcategories).toEqual([
    { key: "conversationMessages", tokens: 500 },
    { key: "toolResults", tokens: 50 },
  ]);
});

test("contextUsageDenominator prefers a declared window and falls back to used tokens", () => {
  expect(contextUsageDenominator(_breakdown)).toBe(10000);
  expect(contextUsageDenominator({ ..._breakdown, contextWindow: null })).toBe(
    1000,
  );
  expect(contextUsageDenominator({ ..._breakdown, contextWindow: 0 })).toBe(
    1000,
  );
});

test("contextUsageShare guards against a missing denominator", () => {
  expect(contextUsageShare(250, 1000)).toBe(25);
  expect(contextUsageShare(0, 1000)).toBe(0);
  expect(contextUsageShare(1, 0)).toBeNull();
  expect(contextUsageShare(Number.NaN, 1000)).toBeNull();
  expect(contextUsageShare(1, Number.POSITIVE_INFINITY)).toBeNull();
});

test("withContextUsageWindow keeps the snapshot until another window is known", () => {
  expect(withContextUsageWindow(_breakdown, undefined)).toBe(_breakdown);
  expect(withContextUsageWindow(_breakdown, 10000)).toBe(_breakdown);
});

test("withContextUsageWindow recomputes percentages and remaining space", () => {
  expect(withContextUsageWindow(_breakdown, 4000)).toMatchObject({
    contextWindow: 4000,
    percentage: 25,
    remainingTokens: 3000,
  });
  expect(
    withContextUsageWindow({ ..._breakdown, totalTokens: 5000 }, 4000),
  ).toMatchObject({
    contextWindow: 4000,
    percentage: 125,
    remainingTokens: 0,
  });
  expect(
    withContextUsageWindow({ ..._breakdown, totalTokens: 1 }, 3).percentage,
  ).toBeCloseTo(33.3333, 4);
});

test("withContextUsageWindow keeps sub-tenth precision for the formatter", () => {
  expect(
    withContextUsageWindow({ ..._breakdown, totalTokens: 1 }, 20_000).percentage,
  ).toBeCloseTo(0.005, 6);
});

test("withContextUsageWindow drops window-relative fields without a window", () => {
  for (const contextWindow of [null, 0]) {
    expect(withContextUsageWindow(_breakdown, contextWindow)).toMatchObject({
      contextWindow: null,
      percentage: null,
      remainingTokens: null,
    });
  }
});
