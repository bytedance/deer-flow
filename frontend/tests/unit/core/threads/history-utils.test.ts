import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

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

test("does not filter AI messages whose id collides with an existing tool's tool_call_id", () => {
  // Existing tool message is keyed under `tool:tc-x`; the incoming AI message
  // is keyed under `message:tc-x`. Under namespaced identities these are
  // distinct, so the AI message is kept (the previous behavior of mapping
  // tool_call_id into a single id Set dropped this message by mistake).
  const existing: Message[] = [
    {
      type: "tool",
      id: "t0",
      tool_call_id: "tc-x",
      content: "result",
      name: "tool",
    } as unknown as Message,
  ];
  const incoming: Message[] = [{ type: "ai", id: "tc-x", content: "response" }];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(1);
  expect(result[0]!.id).toBe("tc-x");
});

test("does not filter tool messages whose tool_call_id collides with an existing AI's id", () => {
  // Symmetric inverse of the previous test: existing AI is keyed under
  // `message:tc-x`; incoming tool is keyed under `tool:tc-x`. Namespaced
  // identities must keep them distinct in this direction as well.
  const existing: Message[] = [{ type: "ai", id: "tc-x", content: "response" }];
  const incoming: Message[] = [
    {
      type: "tool",
      id: "t0",
      tool_call_id: "tc-x",
      content: "result",
      name: "tool",
    } as unknown as Message,
  ];

  const result = deduplicateHistoryMessages(existing, incoming);
  expect(result).toHaveLength(1);
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
  // 3 runs existed, all loaded (index = -1), now 5 runs. Under newest-first
  // ordering the 2 new runs prepend at index 0, so the previous newest
  // (old index 0) is now at index 2.
  const result = adjustHistoryIndex(-1, 3, 5);
  expect(result).toBe(2);
});

test("shifts index by number of added runs when some are unloaded", () => {
  // 3 runs, currently at index 1 (run at index 2 loaded), now 6 runs. Under
  // newest-first ordering the 3 new runs prepend at index 0, so the user's
  // run at old index 1 shifts to index 4.
  const result = adjustHistoryIndex(1, 3, 6);
  expect(result).toBe(4);
});

test("handles single new run when all previous were loaded", () => {
  // 4 runs, all loaded (index = -1), now 5 runs. Under newest-first ordering
  // the 1 new run prepends at index 0, so the previous newest (old index 0)
  // is now at index 1.
  const result = adjustHistoryIndex(-1, 4, 5);
  expect(result).toBe(1);
});

test("handles transition from empty runs to populated", () => {
  // 0 runs → 3 runs, all loaded (index = -1). There was no previous run, so
  // land on the newest (index 0) regardless of new runs length.
  const result = adjustHistoryIndex(-1, 0, 3);
  expect(result).toBe(0);
});
