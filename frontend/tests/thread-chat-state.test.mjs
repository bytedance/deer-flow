import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/components/workspace/chats/thread-chat-state.js"),
).href;

async function importThreadChatStateHelpers() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return {
    reduceThreadChatState: imported.reduceThreadChatState,
    shouldShowNewThreadLayout: imported.shouldShowNewThreadLayout,
  };
}

void test("stale /new pathname does not revert a started chat back to draft state", async () => {
  const { reduceThreadChatState } = await importThreadChatStateHelpers();
  const started = {
    threadId: "real-thread-id",
    persistedThreadId: "real-thread-id",
  };

  const next = reduceThreadChatState(started, {
    pathname: "/workspace/chats/new",
    threadIdFromPath: "new",
    nextDraftThreadId: "draft-thread-id-2",
  });

  assert.deepEqual(next, started);
});

void test("new chat route keeps the existing draft thread id while already in draft mode", async () => {
  const { reduceThreadChatState } = await importThreadChatStateHelpers();
  const draft = {
    threadId: "draft-thread-id-1",
    persistedThreadId: null,
  };

  const next = reduceThreadChatState(draft, {
    pathname: "/workspace/chats/new",
    threadIdFromPath: "new",
    nextDraftThreadId: "draft-thread-id-2",
  });

  assert.deepEqual(next, draft);
});

void test("new thread layout hides once optimistic messages exist", async () => {
  const { shouldShowNewThreadLayout } = await importThreadChatStateHelpers();

  assert.equal(
    shouldShowNewThreadLayout({
      isNewThread: true,
      messageCount: 1,
    }),
    false,
  );
});
