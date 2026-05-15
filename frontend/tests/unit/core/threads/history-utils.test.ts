import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  adjustHistoryIndex,
  deduplicateHistoryMessages,
} from "@/core/threads/history-utils";

// ---------------------------------------------------------------------------
// deduplicateHistoryMessages
// ---------------------------------------------------------------------------

test("returns all incoming messages when existing history is empty", () => {
  const existing: Message[] = [];
  const incoming: Message[] = [
    { type: "human", id: "m1", content: "hello" },
    { type: "ai", id: "m2", content: "hi" },
  ];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(2);
  expect(result.map((m) => m.id)).toEqual(["m1", "m2"]);
});

test("filters out messages whose id already exists in history", () => {
  const existing: Message[] = [
    { type: "human", id: "m1", content: "hello" },
    { type: "ai", id: "m2", content: "hi" },
  ];
  const incoming: Message[] = [
    { type: "human", id: "m1", content: "hello" }, // duplicate
    { type: "ai", id: "m3", content: "new" },
  ];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(1);
  expect(result[0]!.id).toBe("m3");
});

test("filters out tool messages by tool_call_id", () => {
  const existing: Message[] = [
    {
      type: "tool",
      id: "t1",
      tool_call_id: "tc-1",
      content: "tool result",
      name: "search",
    } as unknown as Message,
  ];
  const incoming: Message[] = [
    {
      type: "tool",
      id: "t1-dup",
      tool_call_id: "tc-1",
      content: "tool result",
      name: "search",
    } as unknown as Message,
    {
      type: "tool",
      id: "t2",
      tool_call_id: "tc-2",
      content: "other result",
      name: "search",
    } as unknown as Message,
  ];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(1);
  expect(result[0]!.id).toBe("t2");
});

test("keeps messages with no id or tool_call_id", () => {
  const existing: Message[] = [
    { type: "human", id: "m1", content: "existing" },
  ];
  const incoming: Message[] = [
    // Message without id — should be kept (not considered a duplicate)
    { type: "ai", content: "no id" } as Message,
  ];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(1);
});

test("deduplicates against tool_call_id from existing messages", () => {
  // Existing message has tool_call_id stored in the id set
  const existing: Message[] = [
    {
      type: "tool",
      id: "t0",
      tool_call_id: "tc-x",
      content: "result",
      name: "tool",
    } as unknown as Message,
  ];
  // Incoming AI message references the same id — should be filtered
  const incoming: Message[] = [{ type: "ai", id: "tc-x", content: "response" }];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// adjustHistoryIndex
// ---------------------------------------------------------------------------

test("returns unchanged index when no new runs were added", () => {
  expect(adjustHistoryIndex(2, 5, 5)).toBe(2);
  expect(adjustHistoryIndex(-1, 3, 3)).toBe(-1);
  expect(adjustHistoryIndex(0, 1, 0)).toBe(0); // shouldn't happen, but safe
});

test("resets to last run when all previous runs were loaded", () => {
  // 3 runs existed, all loaded (index = -1), now 5 runs
  const result = adjustHistoryIndex(-1, 3, 5);
  expect(result).toBe(4); // last index of new runs list
});

test("shifts index by number of added runs when some are unloaded", () => {
  // 3 runs, currently at index 1 (run at index 2 loaded), now 6 runs
  const result = adjustHistoryIndex(1, 3, 6);
  // 3 new runs added, shift: 1 + (6 - 3) = 4
  expect(result).toBe(4);
});

test("handles single new run when all previous were loaded", () => {
  // 4 runs, all loaded (index = -1), now 5 runs
  const result = adjustHistoryIndex(-1, 4, 5);
  expect(result).toBe(4);
});

test("handles transition from empty runs to populated", () => {
  // 0 runs → 3 runs, all loaded (index = -1)
  const result = adjustHistoryIndex(-1, 0, 3);
  expect(result).toBe(2);
});
