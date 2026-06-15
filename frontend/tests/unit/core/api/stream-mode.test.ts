import { expect, test } from "vitest";

import { sanitizeRunStreamOptions, STREAM_MODE_TIERS } from "@/core/api/stream-mode";

test("drops unsupported stream modes from array payloads", () => {
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

  expect(sanitized.streamMode).toEqual([
    "values",
    "messages-tuple",
    "custom",
    "updates",
    "events",
  ]);
});

test("drops unsupported stream modes from scalar payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: "tools",
  });

  expect(sanitized.streamMode).toBeUndefined();
});

test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  expect(sanitizeRunStreamOptions(options)).toBe(options);
});

test("standard tier excludes values mode", () => {
  expect(STREAM_MODE_TIERS.standard).not.toContain("values");
  expect(STREAM_MODE_TIERS.standard).toContain("messages-tuple");
  expect(STREAM_MODE_TIERS.standard).toContain("updates");
  expect(STREAM_MODE_TIERS.standard).toContain("custom");
});

test("full tier includes values mode", () => {
  expect(STREAM_MODE_TIERS.full).toContain("values");
  expect(STREAM_MODE_TIERS.full).toContain("messages-tuple");
  expect(STREAM_MODE_TIERS.full).toContain("updates");
  expect(STREAM_MODE_TIERS.full).toContain("custom");
});

test("standard tier has exactly 3 modes", () => {
  expect(STREAM_MODE_TIERS.standard).toHaveLength(3);
});

test("full tier has exactly 4 modes", () => {
  expect(STREAM_MODE_TIERS.full).toHaveLength(4);
});
