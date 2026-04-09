import assert from "node:assert/strict";
import test from "node:test";

const { pathOfThread } = await import(
  new URL("./utils.ts", import.meta.url).href
);

void test("uses standard chat route when thread has no agent context", () => {
  assert.equal(pathOfThread("thread-123"), "/workspace/chats/thread-123");
  assert.equal(
    pathOfThread({
      thread_id: "thread-123",
    }),
    "/workspace/chats/thread-123",
  );
});

void test("uses agent chat route when thread context has agent_name", () => {
  assert.equal(
    pathOfThread({
      thread_id: "thread-123",
      context: { agent_name: "researcher" },
    }),
    "/workspace/agents/researcher/chats/thread-123",
  );
});

void test("uses provided context when pathOfThread is called with a thread id", () => {
  assert.equal(
    pathOfThread("thread-123", { agent_name: "ops agent" }),
    "/workspace/agents/ops%20agent/chats/thread-123",
  );
});
