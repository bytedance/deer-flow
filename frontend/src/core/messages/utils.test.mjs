import assert from "node:assert/strict";
import test from "node:test";

const { getToolCalls } = await import(
  new URL("./utils.ts", import.meta.url).href
);

/**
 * @param {Record<string, unknown>} overrides
 */
function createMessage(overrides = {}) {
  return {
    type: "ai",
    id: "message-1",
    content: "",
    ...overrides,
  };
}

void test("returns tool calls from normal arrays with object args", () => {
  const message = createMessage({
    tool_calls: [
      {
        id: "tool-1",
        name: "bash",
        args: {
          command: "echo hello",
          description: "run hello",
        },
      },
    ],
  });

  assert.deepEqual(getToolCalls(message), [
    {
      id: "tool-1",
      name: "bash",
      args: {
        command: "echo hello",
        description: "run hello",
      },
    },
  ]);
});

void test("parses stringified args inside tool call arrays", () => {
  const message = createMessage({
    tool_calls: [
      {
        id: "tool-1",
        name: "bash",
        args: '{"command":"echo hello"}',
      },
    ],
  });

  assert.deepEqual(getToolCalls(message), [
    {
      id: "tool-1",
      name: "bash",
      args: {
        command: "echo hello",
      },
    },
  ]);
});

void test("parses stringified tool_calls arrays", () => {
  const message = createMessage({
    tool_calls:
      '[{"id":"tool-1","name":"bash","args":{"command":"echo hello"}}]',
  });

  assert.deepEqual(getToolCalls(message), [
    {
      id: "tool-1",
      name: "bash",
      args: {
        command: "echo hello",
      },
    },
  ]);
});

void test("salvages malformed stringified args with unescaped JSON", () => {
  const message = createMessage({
    tool_calls: '[{"id":"1","name":"bash","args":"{"command":"echo hello"}"}]',
  });

  assert.deepEqual(getToolCalls(message), [
    {
      id: "1",
      name: "bash",
      args: {
        command: "echo hello",
      },
    },
  ]);
});

void test("returns an empty array for non-ai messages", () => {
  const message = createMessage({
    type: "tool",
    name: "bash",
  });

  assert.deepEqual(getToolCalls(message), []);
});

void test("returns an empty array when tool_calls is null or undefined", () => {
  const nullMessage = createMessage({
    tool_calls: null,
  });
  const undefinedMessage = createMessage({
    tool_calls: undefined,
  });

  assert.deepEqual(getToolCalls(nullMessage), []);
  assert.deepEqual(getToolCalls(undefinedMessage), []);
});
