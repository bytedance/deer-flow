import assert from "node:assert/strict";
import test from "node:test";

const { sanitizeRunStreamOptions } = await import(
  new URL("./stream-mode.ts", import.meta.url).href
);

void test("keeps supported stream modes in array payloads", () => {
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
    "tools",
  ]);
});

void test("drops unsupported stream modes from scalar payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: "bogus-mode",
  });

  assert.equal(sanitized.streamMode, undefined);
});

void test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  assert.equal(sanitizeRunStreamOptions(options), options);
});
