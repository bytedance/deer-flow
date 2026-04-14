import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/core/threads/optimistic-message-state.js"),
).href;

async function importHelper() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return imported.shouldClearOptimisticMessages;
}

void test("does not clear optimistic human message when only assistant thinking arrives", async () => {
  const shouldClearOptimisticMessages = await importHelper();

  assert.equal(
    shouldClearOptimisticMessages({
      optimisticCount: 1,
      serverMessages: [
        {
          type: "ai",
          content: "",
          additional_kwargs: { reasoning_content: "thinking" },
        },
      ],
    }),
    false,
  );
});
