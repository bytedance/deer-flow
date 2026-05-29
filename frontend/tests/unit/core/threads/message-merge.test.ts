import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  getSummarizationMiddlewareMessages,
  getVisibleOptimisticMessages,
  mergeMessages,
} from "@/core/threads/hooks";

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

test("mergeMessages keeps persisted AI prefix when reconnect stream resumes with only new text", () => {
  const human = {
    id: "human-1",
    type: "human",
    content: "write a report",
  } as Message;
  const persistedAiPrefix = {
    id: "ai-1",
    type: "ai",
    content: "The first section is already persisted. ",
  } as Message;
  const reconnectedAiDelta = {
    id: "ai-1",
    type: "ai",
    content: "The second section arrives after navigation.",
  } as Message;

  expect(
    mergeMessages([human, persistedAiPrefix], [reconnectedAiDelta], [], true),
  ).toEqual([
    human,
    {
      ...reconnectedAiDelta,
      content:
        "The first section is already persisted. The second section arrives after navigation.",
    },
  ]);
});

test("mergeMessages keeps persisted AI prefix for stream-metadata deltas without text overlap", () => {
  const persistedAiPrefix = {
    id: "ai-1",
    type: "ai",
    content: "已经输出的一百个字",
  } as Message;
  const reconnectedAiDelta = {
    id: "ai-1",
    type: "ai",
    content: "继续输出后续内容",
  } as Message;

  expect(
    mergeMessages([persistedAiPrefix], [reconnectedAiDelta], [], () => true),
  ).toEqual([
    {
      ...reconnectedAiDelta,
      content: "已经输出的一百个字继续输出后续内容",
    },
  ]);
});

test("mergeMessages does not duplicate overlapping AI text when reconnect stream repeats the tail", () => {
  const persistedAiPrefix = {
    id: "ai-1",
    type: "ai",
    content: "The answer starts here and ",
  } as Message;
  const reconnectedAiDelta = {
    id: "ai-1",
    type: "ai",
    content: "and continues here.",
  } as Message;

  expect(
    mergeMessages([persistedAiPrefix], [reconnectedAiDelta], [], true),
  ).toEqual([
    {
      ...reconnectedAiDelta,
      content: "The answer starts here and continues here.",
    },
  ]);
});

test("mergeMessages leaves full live AI text unchanged when it already contains history", () => {
  const persistedAiPrefix = {
    id: "ai-1",
    type: "ai",
    content: "partial",
  } as Message;
  const liveFullAi = {
    id: "ai-1",
    type: "ai",
    content: "partial response",
  } as Message;

  expect(mergeMessages([persistedAiPrefix], [liveFullAi], [], true)).toEqual([
    liveFullAi,
  ]);
});

test("mergeMessages does not stitch unrelated live AI replacement text while streaming", () => {
  const persistedAi = {
    id: "ai-1",
    type: "ai",
    content: "old answer",
  } as Message;
  const liveReplacementAi = {
    id: "ai-1",
    type: "ai",
    content: "new answer",
    response_metadata: { model: "test-model" },
  } as Message;

  expect(mergeMessages([persistedAi], [liveReplacementAi], [], true)).toEqual([
    liveReplacementAi,
  ]);
});

test("mergeMessages does not stitch same-id live AI text without stream metadata", () => {
  const persistedAi = {
    id: "ai-1",
    type: "ai",
    content: "已经保存的旧文本",
  } as Message;
  const liveReplacementAi = {
    id: "ai-1",
    type: "ai",
    content: "新的完整替换文本",
  } as Message;

  expect(
    mergeMessages([persistedAi], [liveReplacementAi], [], () => false),
  ).toEqual([liveReplacementAi]);
});

test("mergeMessages keeps live AI metadata when reconnect stream repeats the persisted suffix", () => {
  const persistedAiPrefix = {
    id: "ai-1",
    type: "ai",
    content: "The answer starts here.",
  } as Message;
  const reconnectedAiSuffix = {
    id: "ai-1",
    type: "ai",
    content: "starts here.",
    response_metadata: { model: "test-model" },
  } as Message;

  expect(
    mergeMessages([persistedAiPrefix], [reconnectedAiSuffix], [], true),
  ).toEqual([
    {
      ...reconnectedAiSuffix,
      content: "The answer starts here.",
    },
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
