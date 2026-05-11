import { expect, test } from "vitest";

import { sanitizeRunStreamOptions } from "@/core/api/stream-mode";

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
