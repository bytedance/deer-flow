import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  createMessageBaseline,
  getMessagesAfterBaseline,
  getPendingStreamMessages,
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

test("getMessagesAfterBaseline treats an empty baseline as initialized", () => {
  const firstAi = {
    id: "ai-1",
    type: "ai",
    content: "First answer",
  } as Message;

  expect(
    getMessagesAfterBaseline([firstAi], createMessageBaseline([])),
  ).toEqual([firstAi]);
});

test("getMessagesAfterBaseline includes same-id streaming message updates", () => {
  const baselineAi = {
    id: "ai-1",
    type: "ai",
    content: "Partial",
  } as Message;
  const updatedAi = {
    id: "ai-1",
    type: "ai",
    content: "Partial answer",
  } as Message;

  expect(
    getMessagesAfterBaseline([updatedAi], createMessageBaseline([baselineAi])),
  ).toEqual([updatedAi]);
});

test("getMessagesAfterBaseline ignores same-id metadata-only changes", () => {
  const baselineAi = {
    id: "ai-1",
    type: "ai",
    content: "Completed answer",
    response_metadata: { finish_reason: "stop" },
  } as Message;
  const updatedMetadataAi = {
    id: "ai-1",
    type: "ai",
    content: "Completed answer",
    response_metadata: { finish_reason: "stop", model_name: "gpt-4o" },
    usage_metadata: {
      input_tokens: 1,
      output_tokens: 2,
      total_tokens: 3,
    },
  } as Message;

  expect(
    getMessagesAfterBaseline(
      [updatedMetadataAi],
      createMessageBaseline([baselineAi]),
    ),
  ).toEqual([]);
});

test("getMessagesAfterBaseline excludes unchanged same-id historical messages", () => {
  const baselineAi = {
    id: "ai-1",
    type: "ai",
    content: "Completed answer",
  } as Message;
  const unchangedAi = {
    id: "ai-1",
    type: "ai",
    content: "Completed answer",
  } as Message;

  expect(
    getMessagesAfterBaseline(
      [unchangedAi],
      createMessageBaseline([baselineAi]),
    ),
  ).toEqual([]);
});

test("getMessagesAfterBaseline excludes rebuilt id-less historical messages", () => {
  const historicalAi = {
    type: "ai",
    content: "Completed answer",
  } as Message;
  const rebuiltHistoricalAi = {
    type: "ai",
    content: "Completed answer",
  } as Message;

  expect(
    getMessagesAfterBaseline(
      [rebuiltHistoricalAi],
      createMessageBaseline([historicalAi]),
    ),
  ).toEqual([]);
});

test("getMessagesAfterBaseline preserves duplicate messages beyond the baseline count", () => {
  const firstAi = {
    type: "ai",
    content: "Duplicate",
  } as Message;
  const rebuiltFirstAi = {
    type: "ai",
    content: "Duplicate",
  } as Message;
  const secondAi = {
    type: "ai",
    content: "Duplicate",
  } as Message;

  expect(
    getMessagesAfterBaseline(
      [rebuiltFirstAi, secondAi],
      createMessageBaseline([firstAi]),
    ),
  ).toEqual([secondAi]);
});

test("getMessagesAfterBaseline does not treat raw message fields as snapshots", () => {
  const messageWithSnapshotLikeFields = {
    id: "ai-1",
    type: "ai",
    content: "Visible answer",
    message: {
      id: "nested-ai",
      type: "ai",
      content: "Nested object",
    },
    fingerprint: "backend-field",
  } as unknown as Message;

  expect(
    getMessagesAfterBaseline(
      [messageWithSnapshotLikeFields],
      createMessageBaseline([]),
    ),
  ).toEqual([messageWithSnapshotLikeFields]);
});

test("getPendingStreamMessages includes SDK streaming metadata without a local baseline", () => {
  const historicalAi = {
    id: "ai-1",
    type: "ai",
    content: "Completed answer",
  } as Message;
  const streamingAi = {
    id: "ai-2",
    type: "ai",
    content: "Partial",
  } as Message;

  expect(
    getPendingStreamMessages([historicalAi, streamingAi], {
      isLoading: true,
      baseline: createMessageBaseline([]),
      baselineInitialized: false,
      getMessagesMetadata: (message) =>
        message === streamingAi
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
    }),
  ).toEqual([streamingAi]);
});
