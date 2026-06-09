import type { Message, Run } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  buildRunMessagesUrl,
  findLatestUnloadedRunIndex,
  getNextRunMessagesBeforeSeq,
  getOldestRunMessageSeq,
  getSummarizationMiddlewareMessages,
  getVisibleOptimisticMessages,
  MAX_CONSECUTIVE_EMPTY_RUN_LOADS,
  mergeMessages,
  runMessagesPageHasMore,
  shouldAutoContinueOnEmptyRun,
} from "@/core/threads/hooks";
import type { RunMessage } from "@/core/threads/types";

function runMessage(seq?: number): RunMessage {
  return {
    run_id: "run-1",
    ...(seq === undefined ? {} : { seq }),
    content: {} as Message,
    metadata: { caller: "" },
    created_at: "2026-05-22T00:00:00Z",
  };
}

test("mergeMessages removes duplicate messages already present in history", () => {
  const human = {
    id: "human-1",
    type: "human",
    content: "Design an agent",
  } as Message;
  const ai = {
    id: "ai-1",
    type: "ai",
    content: "Let's design it.",
  } as Message;

  expect(mergeMessages([human, ai, human, ai], [], [])).toEqual([human, ai]);
});

test("mergeMessages lets live thread messages replace overlapping history", () => {
  const oldHuman = {
    id: "human-1",
    type: "human",
    content: "old",
  } as Message;
  const liveHuman = {
    id: "human-1",
    type: "human",
    content: "live",
  } as Message;
  const oldAi = {
    id: "ai-1",
    type: "ai",
    content: "old",
  } as Message;
  const liveAi = {
    id: "ai-1",
    type: "ai",
    content: "live",
  } as Message;

  expect(mergeMessages([oldHuman, oldAi], [liveHuman, liveAi], [])).toEqual([
    liveHuman,
    liveAi,
  ]);
});

test("mergeMessages deduplicates tool messages by tool_call_id", () => {
  const oldTool = {
    id: "tool-message-old",
    type: "tool",
    tool_call_id: "call-1",
    content: "old",
  } as Message;
  const liveTool = {
    id: "tool-message-live",
    type: "tool",
    tool_call_id: "call-1",
    content: "live",
  } as Message;

  expect(mergeMessages([oldTool], [liveTool], [])).toEqual([liveTool]);
});

test("mergeMessages keeps a visible history message when a hidden live message reuses its id", () => {
  const historyHuman = {
    id: "human-1",
    type: "human",
    content: "visible user prompt",
  } as Message;
  const hiddenReminder = {
    id: "human-1",
    type: "human",
    content: "<system-reminder>hidden</system-reminder>",
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const liveAi = {
    id: "ai-1",
    type: "ai",
    content: "live answer",
  } as Message;

  expect(mergeMessages([historyHuman], [hiddenReminder, liveAi], [])).toEqual([
    historyHuman,
    liveAi,
  ]);
});

test("mergeMessages lets a visible live message replace overlapping hidden history", () => {
  const hiddenHistoryHuman = {
    id: "human-1",
    type: "human",
    content: "<system-reminder>hidden</system-reminder>",
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const liveHuman = {
    id: "human-1",
    type: "human",
    content: "visible user prompt",
  } as Message;

  expect(mergeMessages([hiddenHistoryHuman], [liveHuman], [])).toEqual([
    liveHuman,
  ]);
});

test("getSummarizationMiddlewareMessages matches DeerFlow summarization update keys", () => {
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "DeerFlowSummarizationMiddleware.before_model": {
        messages: [removeAll, summary],
      },
    }),
  ).toEqual([removeAll, summary]);
});

test("getSummarizationMiddlewareMessages matches base LangChain summarization update keys", () => {
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "SummarizationMiddleware.before_model": {
        messages: [summary],
      },
    }),
  ).toEqual([summary]);
});

test("getSummarizationMiddlewareMessages ignores unrelated suffix-sharing update keys", () => {
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "OtherSummarizationMiddleware.before_model": {
        messages: [summary],
      },
    }),
  ).toBeUndefined();
});

test("getVisibleOptimisticMessages hides optimistic user input after server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 0, 1)).toEqual([]);
});

test("mergeMessages shows server human instead of optimistic duplicate after first response", () => {
  const serverHuman = {
    id: "server-human-1",
    type: "human",
    content: "hello",
  } as Message;
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;
  const visibleOptimistic = getVisibleOptimisticMessages(
    [optimisticHuman],
    0,
    1,
  );

  expect(mergeMessages([], [serverHuman], visibleOptimistic)).toEqual([
    serverHuman,
  ]);
});

test("getVisibleOptimisticMessages keeps optimistic user input until server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 0, 0)).toEqual([
    optimisticHuman,
  ]);
});

test("getVisibleOptimisticMessages keeps non-human optimistic status messages", () => {
  const optimisticAi = {
    id: "opt-ai-1",
    type: "ai",
    content: "Uploading files...",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticAi], 0, 1)).toEqual([
    optimisticAi,
  ]);
});

test("getVisibleOptimisticMessages hides the upload optimistic pair after server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "upload this",
  } as Message;
  const optimisticUploadingAi = {
    id: "opt-ai-uploading",
    type: "ai",
    content: "Uploading files...",
  } as Message;

  expect(
    getVisibleOptimisticMessages(
      [optimisticHuman, optimisticUploadingAi],
      0,
      1,
    ),
  ).toEqual([]);
});

test("getVisibleOptimisticMessages hides optimistic user input after later server turns", () => {
  const optimisticHuman = {
    id: "opt-human-2",
    type: "human",
    content: "follow up",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 3, 4)).toEqual([]);
  expect(getVisibleOptimisticMessages([optimisticHuman], 3, 3)).toEqual([
    optimisticHuman,
  ]);
});

test("runMessagesPageHasMore reads backend snake_case pagination field", () => {
  expect(runMessagesPageHasMore({ data: [], has_more: true })).toBe(true);
  expect(runMessagesPageHasMore({ data: [], has_more: false })).toBe(false);
});

test("runMessagesPageHasMore keeps compatibility with camelCase pagination field", () => {
  expect(runMessagesPageHasMore({ data: [], hasMore: true })).toBe(true);
});

test("getOldestRunMessageSeq returns the cursor for the next older run page", () => {
  expect(
    getOldestRunMessageSeq([runMessage(8), runMessage(9), runMessage(10)]),
  ).toBe(8);
});

test("getOldestRunMessageSeq ignores rows without seq", () => {
  expect(getOldestRunMessageSeq([runMessage()])).toBeNull();
});

test("getNextRunMessagesBeforeSeq keeps runs pending when has_more lacks seq", () => {
  expect(
    getNextRunMessagesBeforeSeq({ data: [runMessage()], has_more: true }),
  ).toBeUndefined();
});

test("getNextRunMessagesBeforeSeq marks runs loaded when no more pages exist", () => {
  expect(
    getNextRunMessagesBeforeSeq({ data: [runMessage()], has_more: false }),
  ).toBeNull();
});

test("buildRunMessagesUrl encodes path segments and optional before_seq", () => {
  expect(
    buildRunMessagesUrl(
      "https://api.example.test/",
      "thread/with space",
      "run?one",
      18,
    ),
  ).toBe(
    "https://api.example.test/api/threads/thread%2Fwith%20space/runs/run%3Fone/messages?before_seq=18",
  );
});

test("buildRunMessagesUrl omits before_seq when loading the latest page", () => {
  expect(
    buildRunMessagesUrl("https://api.example.test", "thread-1", "run-1"),
  ).toBe("https://api.example.test/api/threads/thread-1/runs/run-1/messages");
});

test("buildRunMessagesUrl returns a relative URL when using the nginx proxy", () => {
  expect(buildRunMessagesUrl("", "thread-1", "run-1", 42)).toBe(
    "/api/threads/thread-1/runs/run-1/messages?before_seq=42",
  );
});

test("findLatestUnloadedRunIndex loads the newest run first from a newest-first list", () => {
  const runs = [
    { run_id: "R6" },
    { run_id: "R5" },
    { run_id: "R4" },
    { run_id: "R3" },
    { run_id: "R2" },
    { run_id: "R1" },
  ] as unknown as Run[];
  expect(findLatestUnloadedRunIndex(runs, new Set())).toBe(0);
});

test("findLatestUnloadedRunIndex skips already-loaded runs and returns the next newest unloaded run", () => {
  const runs = [
    { run_id: "R6" },
    { run_id: "R5" },
    { run_id: "R4" },
  ] as unknown as Run[];
  expect(findLatestUnloadedRunIndex(runs, new Set(["R6"]))).toBe(1);
});

test("findLatestUnloadedRunIndex returns -1 when every run is already loaded", () => {
  const runs = [{ run_id: "R2" }, { run_id: "R1" }] as unknown as Run[];
  expect(findLatestUnloadedRunIndex(runs, new Set(["R1", "R2"]))).toBe(-1);
});

test("loading runs in newest-first order and prepending pages yields chronological messages (regression for #3352)", () => {
  // Simulate backend list_by_thread returning newest first.
  const runs = [
    { run_id: "R6" },
    { run_id: "R5" },
    { run_id: "R4" },
    { run_id: "R3" },
    { run_id: "R2" },
    { run_id: "R1" },
  ] as unknown as Run[];
  const runIdToContent: Record<string, string> = {
    R1: "A",
    R2: "B",
    R3: "C",
    R4: "D",
    R5: "E",
    R6: "F",
  };

  const loaded = new Set<string>();
  let messages: Message[] = [];

  while (true) {
    const index = findLatestUnloadedRunIndex(runs, loaded);
    if (index === -1) break;
    const run = runs[index]!;
    const pageMessages = [
      {
        id: run.run_id,
        type: "human",
        content: runIdToContent[run.run_id],
      } as Message,
    ];
    // Mirror loadMessages: prepend new page to existing messages.
    messages = [...pageMessages, ...messages];
    loaded.add(run.run_id);
  }

  expect(messages.map((m) => m.content)).toEqual([
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
  ]);
});

test("shouldAutoContinueOnEmptyRun does not continue when the run produced messages", () => {
  expect(shouldAutoContinueOnEmptyRun(3, 0)).toBe(false);
  expect(shouldAutoContinueOnEmptyRun(1, 4)).toBe(false);
});

test("shouldAutoContinueOnEmptyRun continues when an empty run is below the safety cap", () => {
  expect(shouldAutoContinueOnEmptyRun(0, 0)).toBe(true);
  expect(
    shouldAutoContinueOnEmptyRun(0, MAX_CONSECUTIVE_EMPTY_RUN_LOADS - 1),
  ).toBe(true);
});

test("shouldAutoContinueOnEmptyRun stops once consecutive empty loads reach the cap", () => {
  expect(shouldAutoContinueOnEmptyRun(0, MAX_CONSECUTIVE_EMPTY_RUN_LOADS)).toBe(
    false,
  );
  expect(
    shouldAutoContinueOnEmptyRun(0, MAX_CONSECUTIVE_EMPTY_RUN_LOADS + 1),
  ).toBe(false);
});

test("shouldAutoContinueOnEmptyRun honors a custom safety cap when provided", () => {
  expect(shouldAutoContinueOnEmptyRun(0, 0, 1)).toBe(true);
  expect(shouldAutoContinueOnEmptyRun(0, 1, 1)).toBe(false);
});

test("simulating auto-continue across empty runs skips empty contributions and lands on the next run with content (issue #3352 follow-up)", () => {
  const runs = [
    { run_id: "R6" },
    { run_id: "R5" },
    { run_id: "R4" },
    { run_id: "R3" },
    { run_id: "R2" },
    { run_id: "R1" },
  ] as unknown as Run[];
  const runIdToMessages: Record<string, Message[]> = {
    R6: [{ id: "R6", type: "human", content: "F" } as Message],
    R5: [{ id: "R5", type: "human", content: "E" } as Message],
    R4: [],
    R3: [],
    R2: [],
    R1: [{ id: "R1", type: "human", content: "A" } as Message],
  };

  const loaded = new Set<string>();
  let messages: Message[] = [];

  loaded.add("R6");
  loaded.add("R5");
  messages = [...runIdToMessages.R5!, ...runIdToMessages.R6!];

  let consecutiveEmptyLoads = 0;
  let visited = 0;
  const visitedRunIds: string[] = [];
  while (true) {
    const index = findLatestUnloadedRunIndex(runs, loaded);
    if (index === -1) break;
    const run = runs[index]!;
    visited += 1;
    visitedRunIds.push(run.run_id);
    const pageMessages = runIdToMessages[run.run_id] ?? [];
    messages = [...pageMessages, ...messages];
    loaded.add(run.run_id);
    if (
      !shouldAutoContinueOnEmptyRun(pageMessages.length, consecutiveEmptyLoads)
    ) {
      consecutiveEmptyLoads = 0;
      break;
    }
    consecutiveEmptyLoads += 1;
  }

  expect(visitedRunIds).toEqual(["R4", "R3", "R2", "R1"]);
  expect(visited).toBe(4);
  expect(messages.map((m) => m.content)).toEqual(["A", "E", "F"]);
});

test("shouldAutoContinueOnEmptyRun input must use the post-filter visible count, not the raw page size (middleware-only runs should still trigger auto-continue)", () => {
  const filteredVisibleCount = 0;
  const rawPageSize = 3; // pretend the raw page had 3 middleware-only entries
  expect(shouldAutoContinueOnEmptyRun(filteredVisibleCount, 0)).toBe(true);
  expect(shouldAutoContinueOnEmptyRun(rawPageSize, 0)).toBe(false);
});
