import assert from "node:assert/strict";
import test from "node:test";

const { sanitizeRunStreamOptions } = await import(
  new URL("./stream-mode.ts", import.meta.url).href
);

void test("drops unsupported stream modes from array payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: [
      "values",
      "messages-tuple",
      "custom",
      "updates",
      "events",
      "tools",
    ],
  });

  assert.deepEqual(sanitized.streamMode, [
    "values",
    "messages-tuple",
    "custom",
    "updates",
    "events",
  ]);
});

void test("drops unsupported stream modes from scalar payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: "tools",
  });

  assert.equal(sanitized.streamMode, undefined);
});

void test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  assert.equal(sanitizeRunStreamOptions(options), options);
});

void test("returns the same object reference when all modes are supported", () => {
  const options = { streamMode: ["values", "messages-tuple"] };
  assert.equal(sanitizeRunStreamOptions(options), options);
});

void test("keeps supported scalar modes unchanged", () => {
  const options = { streamMode: "values" };
  assert.equal(sanitizeRunStreamOptions(options), options);
});

void test("keeps null streamMode unchanged", () => {
  const options = { streamMode: null };
  assert.equal(sanitizeRunStreamOptions(options), options);
});

void test("preserves supported messages mode in array", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: ["messages", "tools"],
  });
  assert.deepEqual(sanitized.streamMode, ["messages"]);
});

void test("returns empty array when all array modes are unsupported", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: ["tools"],
  });
  assert.deepEqual(sanitized.streamMode, []);
});

void test("passes through non-object options unchanged", () => {
  assert.equal(sanitizeRunStreamOptions(null), null);
  assert.equal(sanitizeRunStreamOptions(undefined), undefined);
});
