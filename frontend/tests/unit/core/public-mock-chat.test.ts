import { test, expect } from "vitest";

import { getPublicMockChatThreadId } from "@/core/public-mock-chat";

const THREAD_ID = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";

test("recognizes public mock chat requests", () => {
  expect(
    getPublicMockChatThreadId(`/workspace/chats/${THREAD_ID}`, "?mock=true"),
  ).toBe(THREAD_ID);
});

test("does not treat protected workspace routes as public mock chats", () => {
  expect(getPublicMockChatThreadId("/workspace/chats/new", "?mock=true")).toBe(
    null,
  );
  expect(getPublicMockChatThreadId("/workspace/chats", "?mock=true")).toBe(
    null,
  );
  expect(
    getPublicMockChatThreadId(
      `/workspace/chats/${THREAD_ID}/artifacts`,
      "?mock=true",
    ),
  ).toBe(null);
  expect(
    getPublicMockChatThreadId(
      `/workspace/agents/researcher/chats/${THREAD_ID}`,
      "?mock=true",
    ),
  ).toBe(null);
});

test("requires explicit mock mode and a UUID thread id", () => {
  expect(getPublicMockChatThreadId(`/workspace/chats/${THREAD_ID}`, "")).toBe(
    null,
  );
  expect(
    getPublicMockChatThreadId(`/workspace/chats/${THREAD_ID}`, "?mock=false"),
  ).toBe(null);
  expect(
    getPublicMockChatThreadId("/workspace/chats/not-a-uuid", "?mock=true"),
  ).toBe(null);
  expect(
    getPublicMockChatThreadId("/workspace/chats/..%2Fsecret", "?mock=true"),
  ).toBe(null);
});
