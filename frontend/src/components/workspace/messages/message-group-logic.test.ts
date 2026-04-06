import assert from "node:assert/strict";
import test from "node:test";

import type { Message } from "@langchain/langgraph-sdk";

const { convertToSteps, getAboveVisibleSteps, getVisibleToolCallSteps } =
  await import(new URL("./message-group-logic.ts", import.meta.url).href);

function createAIMessage({
  id,
  toolCalls = [],
  reasoning,
}: {
  id: string;
  toolCalls?: Array<{
    id: string;
    name: string;
    args: Record<string, unknown>;
  }>;
  reasoning?: string;
}) {
  return {
    id,
    type: "ai",
    content: "",
    additional_kwargs: reasoning ? { reasoning_content: reasoning } : {},
    tool_calls: toolCalls,
  } as Message;
}

function createToolMessage({
  id,
  toolCallId,
  content,
}: {
  id: string;
  toolCallId: string;
  content: string;
}) {
  return {
    id,
    type: "tool",
    name: "web_search",
    tool_call_id: toolCallId,
    content,
  } as Message;
}

void test("keeps the full latest tool batch visible for parallel tool calls", () => {
  const messages: Message[] = [
    createAIMessage({
      id: "ai-1",
      reasoning: "Need to fan out",
      toolCalls: [
        { id: "tool-1", name: "web_search", args: { query: "alpha" } },
        { id: "tool-2", name: "web_search", args: { query: "beta" } },
        { id: "tool-3", name: "web_search", args: { query: "gamma" } },
      ],
    }),
  ];

  const steps = convertToSteps(messages);
  const visibleToolCallSteps = getVisibleToolCallSteps(steps);
  const aboveVisibleSteps = getAboveVisibleSteps(steps, visibleToolCallSteps);

  assert.deepEqual(
    visibleToolCallSteps.map((step) => step.id),
    ["tool-1", "tool-2", "tool-3"],
  );
  assert.deepEqual(
    aboveVisibleSteps.map((step) => step.type),
    ["reasoning"],
  );
});

void test("tracks completion independently inside a parallel tool batch", () => {
  const messages: Message[] = [
    createAIMessage({
      id: "ai-1",
      toolCalls: [
        { id: "tool-1", name: "web_search", args: { query: "alpha" } },
        { id: "tool-2", name: "web_search", args: { query: "beta" } },
        { id: "tool-3", name: "web_search", args: { query: "gamma" } },
      ],
    }),
    createToolMessage({
      id: "tool-msg-2",
      toolCallId: "tool-2",
      content: '[{"title":"beta","url":"https://example.com/beta"}]',
    }),
    createToolMessage({
      id: "tool-msg-3",
      toolCallId: "tool-3",
      content: '[{"title":"gamma","url":"https://example.com/gamma"}]',
    }),
  ];

  const visibleToolCallSteps = getVisibleToolCallSteps(
    convertToSteps(messages),
  );

  assert.deepEqual(
    visibleToolCallSteps.map((step) => ({
      id: step.id,
      isComplete: step.isComplete,
    })),
    [
      { id: "tool-1", isComplete: false },
      { id: "tool-2", isComplete: true },
      { id: "tool-3", isComplete: true },
    ],
  );
});

void test("falls back to only the latest tool batch for sequential tool calls", () => {
  const messages: Message[] = [
    createAIMessage({
      id: "ai-1",
      toolCalls: [
        { id: "tool-1", name: "web_search", args: { query: "alpha" } },
      ],
    }),
    createToolMessage({
      id: "tool-msg-1",
      toolCallId: "tool-1",
      content: '[{"title":"alpha","url":"https://example.com/alpha"}]',
    }),
    createAIMessage({
      id: "ai-2",
      toolCalls: [
        { id: "tool-2", name: "web_search", args: { query: "beta" } },
      ],
    }),
  ];

  const steps = convertToSteps(messages);
  const visibleToolCallSteps = getVisibleToolCallSteps(steps);
  const aboveVisibleSteps = getAboveVisibleSteps(steps, visibleToolCallSteps);

  assert.deepEqual(
    visibleToolCallSteps.map((step) => step.id),
    ["tool-2"],
  );
  assert.deepEqual(
    aboveVisibleSteps
      .filter((step) => step.type === "toolCall")
      .map((step) => step.id),
    ["tool-1"],
  );
});
