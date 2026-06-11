import { expect, test } from "vitest";

import { channelSourceOfThread, pathOfThread } from "@/core/threads/utils";

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

test("reads IM channel source metadata", () => {
  expect(
    channelSourceOfThread({
      metadata: {
        channel_source: {
          type: "im_channel",
          provider: "feishu",
          chat_id: "oc_123",
        },
      },
    }),
  ).toEqual({
    type: "im_channel",
    provider: "feishu",
    label: "Feishu",
  });
});

test("ignores threads without valid IM channel source metadata", () => {
  expect(channelSourceOfThread({ metadata: {} })).toBeNull();
  expect(
    channelSourceOfThread({
      metadata: { channel_source: { provider: "" } },
    }),
  ).toBeNull();
  expect(
    channelSourceOfThread({
      metadata: {
        channel_source: {
          type: "other",
          provider: "feishu",
        },
      },
    }),
  ).toBeNull();
});
