import assert from "node:assert/strict";
import test from "node:test";

const { sanitizeRunStreamOptions, warnUnsupportedStreamModes } = await import(
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

// tools mode is now supported after the SDK upgrade
void test("tools is a supported stream mode", () => {
  const sanitized = sanitizeRunStreamOptions({ streamMode: "tools" });
  assert.equal(sanitized.streamMode, "tools");
});

void test("tools survives array filtering", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: ["tools", "values"],
  });
  assert.deepEqual(sanitized.streamMode, ["tools", "values"]);
});

void test("all known supported modes pass through as scalars", () => {
  const supported = [
    "values",
    "messages",
    "messages-tuple",
    "updates",
    "events",
    "debug",
    "tasks",
    "checkpoints",
    "custom",
    "tools",
  ];
  for (const mode of supported) {
    const result = sanitizeRunStreamOptions({ streamMode: mode });
    assert.equal(result.streamMode, mode, `Expected ${mode} to be supported`);
  }
});

void test("returns same object reference when no modes are dropped", () => {
  const options = { streamMode: ["values", "tools"], streamSubgraphs: true };
  const result = sanitizeRunStreamOptions(options);
  assert.equal(result, options);
});

void test("drops unsupported modes from mixed array, keeps supported", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: ["values", "bogus", "tools", "unknown"],
  });
  assert.deepEqual(sanitized.streamMode, ["values", "tools"]);
});

void test("array with all unsupported modes returns empty array", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: ["bogus", "unknown", "fake"],
  });
  assert.deepEqual(sanitized.streamMode, []);
});

void test("null streamMode is returned unchanged", () => {
  const options = { streamMode: null, streamSubgraphs: true };
  const result = sanitizeRunStreamOptions(options);
  assert.equal(result, options);
});

void test("non-object input passes through untouched", () => {
  assert.equal(sanitizeRunStreamOptions("string" as unknown as object), "string");
  assert.equal(sanitizeRunStreamOptions(null as unknown as object), null);
  assert.equal(sanitizeRunStreamOptions(42 as unknown as object), 42);
});

void test("preserves extra options alongside streamMode when filtering", () => {
  const result = sanitizeRunStreamOptions({
    streamMode: ["values", "bogus"],
    streamSubgraphs: true,
  });
  assert.deepEqual(result.streamMode, ["values"]);
  assert.equal((result as { streamSubgraphs: boolean }).streamSubgraphs, true);
});

void test("warnUnsupportedStreamModes calls warn with mode names", () => {
  const warnings: string[] = [];
  warnUnsupportedStreamModes(["warn-test-mode-1"], (msg: string) => warnings.push(msg));
  assert.equal(warnings.length, 1);
  assert.ok(warnings[0].includes("warn-test-mode-1"));
});

void test("warnUnsupportedStreamModes deduplicates repeated modes", () => {
  const warnings: string[] = [];
  const warn = (msg: string) => warnings.push(msg);
  warnUnsupportedStreamModes(["dedupe-mode-unique-1"], warn);
  warnUnsupportedStreamModes(["dedupe-mode-unique-1"], warn);
  assert.equal(warnings.length, 1);
});

void test("warnUnsupportedStreamModes does nothing for empty array", () => {
  const warnings: string[] = [];
  warnUnsupportedStreamModes([], (msg: string) => warnings.push(msg));
  assert.equal(warnings.length, 0);
});
