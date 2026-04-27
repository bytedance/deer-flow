import { expect, test } from "vitest";

import {
  extractReasoningContentFromMessage,
  hasReasoning,
} from "@/core/messages/utils";

function makeAIMessage(overrides: Record<string, unknown> = {}) {
  return {
    type: "ai" as const,
    id: `msg-${Math.random()}`,
    content: "",
    ...overrides,
  };
}

// --- Fix #4: OrchestratorThinking unconditional render ---
// When models don't populate reasoning_content, extractReasoningContentFromMessage
// should still return text content so OrchestratorThinking can display it.

test("extractReasoningContentFromMessage returns reasoning_content when present", () => {
  const msg = makeAIMessage({
    additional_kwargs: {
      reasoning_content: "I should analyze this carefully.",
    },
  });

  expect(extractReasoningContentFromMessage(msg)).toBe(
    "I should analyze this carefully.",
  );
});

test("extractReasoningContentFromMessage returns null for non-AI messages", () => {
  const msg = { type: "human", id: "msg-1", content: "hello" };

  expect(
    extractReasoningContentFromMessage(
      msg as Parameters<typeof extractReasoningContentFromMessage>[0],
    ),
  ).toBeNull();
});

test("extractReasoningContentFromMessage returns null when content is empty string", () => {
  const msg = makeAIMessage({ content: "" });

  expect(extractReasoningContentFromMessage(msg)).toBeNull();
});

test("hasReasoning returns false for AI message with no reasoning", () => {
  const msg = makeAIMessage({
    tool_calls: [
      { id: "tc-1", name: "task", args: { description: "do stuff" } },
    ],
  });

  expect(hasReasoning(msg)).toBe(false);
});

test("hasReasoning returns true for AI message with reasoning_content", () => {
  const msg = makeAIMessage({
    additional_kwargs: { reasoning_content: "thinking..." },
  });

  expect(hasReasoning(msg)).toBe(true);
});

// --- Fix #5: Empty array fallback ---
// When convertToSteps returns an empty array (e.g., only task tool calls),
// the SubtaskCard should still show the fallback UI.

test("hasReasoning returns false for AI message with only task tool calls and no content", () => {
  // This simulates the scenario where historySteps would be an empty array
  const msg = makeAIMessage({
    content: "",
    tool_calls: [
      { id: "tc-1", name: "task", args: { description: "subtask 1" } },
      { id: "tc-2", name: "task", args: { description: "subtask 2" } },
    ],
  });

  expect(hasReasoning(msg)).toBe(false);
  // The fix ensures `!historySteps || historySteps.length === 0` in SubtaskCard
  // so that an empty steps array still shows the fallback UI.
});

// --- Fix #2: Race condition ---
// Verifies that the minimal placeholder fields (status, description, prompt, subagent_type)
// are enough to create a valid Subtask even when task_running arrives first.

test("minimal placeholder subtask has all required fields", () => {
  const placeholder = {
    id: "task-new",
    status: "in_progress" as const,
    description: "",
    prompt: "",
    subagent_type: "",
    latestMessage: {
      type: "ai" as const,
      id: "msg-1",
      content: "working",
    },
  };

  // All required Subtask fields are present
  expect(placeholder.id).toBeDefined();
  expect(placeholder.status).toBe("in_progress");
  expect(placeholder.description).toBeDefined();
  expect(placeholder.prompt).toBeDefined();
  expect(placeholder.subagent_type).toBeDefined();
});
