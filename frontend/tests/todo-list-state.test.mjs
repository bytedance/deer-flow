import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/components/workspace/todo-list-state.js"),
).href;

async function importShouldRenderTodoQueue() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return imported.shouldRenderTodoQueue;
}

void test("collapsed todo list does not render the scroll area queue", async () => {
  const shouldRenderTodoQueue = await importShouldRenderTodoQueue();

  assert.equal(
    shouldRenderTodoQueue({
      hidden: false,
      collapsed: true,
      todos: [{ content: "first task", status: "pending" }],
    }),
    false,
  );
});

void test("expanded visible todo list renders the scroll area queue", async () => {
  const shouldRenderTodoQueue = await importShouldRenderTodoQueue();

  assert.equal(
    shouldRenderTodoQueue({
      hidden: false,
      collapsed: false,
      todos: [{ content: "first task", status: "pending" }],
    }),
    true,
  );
});
