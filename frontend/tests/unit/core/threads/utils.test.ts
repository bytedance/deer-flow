import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import type { AgentThread } from "@/core/threads/types";
import {
  channelSourceOfThread,
  isThreadPinned,
  pathOfThread,
  sortPinnedThreads,
  textOfMessage,
  THREAD_PINNED_METADATA_KEY,
} from "@/core/threads/utils";

function makeThread(
  threadId: string,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: threadId,
    metadata,
    values: { title: threadId },
  } as unknown as AgentThread;
}

test("uses standard chat route when thread has no agent context", () => {
  expect(pathOfThread("thread-123")).toBe("/workspace/chats/thread-123");
  expect(
    pathOfThread({
      thread_id: "thread-123",
    }),
  ).toBe("/workspace/chats/thread-123");
});

test("encodes thread ids in standard chat routes", () => {
  expect(pathOfThread("thread#1?draft")).toBe(
    "/workspace/chats/thread%231%3Fdraft",
  );
});

test("encodes thread ids in agent chat routes", () => {
  expect(pathOfThread("thread#1?draft", { agent_name: "researcher" })).toBe(
    "/workspace/agents/researcher/chats/thread%231%3Fdraft",
  );
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

test("reads pinned thread metadata strictly from the pinned metadata key", () => {
  expect(
    isThreadPinned(
      makeThread("pinned", { [THREAD_PINNED_METADATA_KEY]: true }),
    ),
  ).toBe(true);
  expect(
    isThreadPinned(
      makeThread("false", { [THREAD_PINNED_METADATA_KEY]: false }),
    ),
  ).toBe(false);
  expect(
    isThreadPinned(
      makeThread("truthy", { [THREAD_PINNED_METADATA_KEY]: "true" }),
    ),
  ).toBe(false);
  expect(isThreadPinned(makeThread("legacy-bare-key", { pinned: true }))).toBe(
    false,
  );
  expect(isThreadPinned(makeThread("missing"))).toBe(false);
});

test("sortPinnedThreads keeps pinned threads first without reordering groups", () => {
  const threads = [
    makeThread("recent-1"),
    makeThread("pinned-1", { [THREAD_PINNED_METADATA_KEY]: true }),
    makeThread("recent-2"),
    makeThread("pinned-2", { [THREAD_PINNED_METADATA_KEY]: true }),
  ];

  expect(sortPinnedThreads(threads).map((thread) => thread.thread_id)).toEqual([
    "pinned-1",
    "pinned-2",
    "recent-1",
    "recent-2",
  ]);
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

test("textOfMessage concatenates object and bare-string content parts", () => {
  // Gemini's finalized shape: first signed {type:text} block + bare-string
  // continuation. textOfMessage joins flat ("") for single-line consumers.
  const message = {
    id: "ai-1",
    type: "ai",
    content: [
      {
        type: "text",
        text: "First block.",
        extras: { signature: "abc123" },
        index: 0,
      },
      " Continuation as a bare string.",
    ],
  } as unknown as Message;

  expect(textOfMessage(message)).toBe(
    "First block. Continuation as a bare string.",
  );
});

test("textOfMessage returns null when array content has no text", () => {
  const message = {
    id: "ai-1",
    type: "ai",
    content: [{ type: "image_url", image_url: "https://example.com/x.png" }],
  } as unknown as Message;

  expect(textOfMessage(message)).toBeNull();
});
