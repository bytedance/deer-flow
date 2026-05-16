import { expect, test } from "vitest";

import { pathOfThread } from "@/core/threads/utils";

test("uses standard chat route when thread has no agent context", () => {
  expect(pathOfThread("thread-123")).toBe("/workspace/chats/thread-123");
  expect(
    pathOfThread({
      thread_id: "thread-123",
    }),
  ).toBe("/workspace/chats/thread-123");
});

test("uses agent chat route when thread context has agent_name", () => {
  expect(
    pathOfThread({
      thread_id: "thread-123",
      context: { agent_name: "researcher" },
    }),
  ).toBe("/workspace/agents/researcher/chats/thread-123");
});

test("uses provided context when pathOfThread is called with a thread id", () => {
  expect(pathOfThread("thread-123", { agent_name: "ops agent" })).toBe(
    "/workspace/agents/ops%20agent/chats/thread-123",
  );
});

test("uses agent chat route when thread metadata has agent_name", () => {
  expect(
    pathOfThread({
      thread_id: "thread-456",
      metadata: { agent_name: "coder" },
    }),
  ).toBe("/workspace/agents/coder/chats/thread-456");
});

test("prefers context.agent_name over metadata.agent_name", () => {
  expect(
    pathOfThread({
      thread_id: "thread-789",
      context: { agent_name: "from-context" },
      metadata: { agent_name: "from-metadata" },
    }),
  ).toBe("/workspace/agents/from-context/chats/thread-789");
});
