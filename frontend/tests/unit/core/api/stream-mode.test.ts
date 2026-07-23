import { expect, test } from "@rstest/core";

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
  ]);
});

test("rejects payloads when every requested stream mode is unsupported", () => {
  expect(() =>
    sanitizeRunStreamOptions({
      streamMode: ["events", "tools"],
    }),
  ).toThrow("No supported LangGraph stream modes remain");

  expect(() =>
    sanitizeRunStreamOptions({
      streamMode: "tools",
    }),
  ).toThrow("No supported LangGraph stream modes remain");
});

test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  expect(sanitizeRunStreamOptions(options)).toBe(options);
});

test("strips streamResumable before sending run options to the API", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamResumable: true,
    streamSubgraphs: true,
  });

  expect(sanitized).toEqual({
    streamSubgraphs: true,
  });
});

test("sanitizes streamResumable and mixed stream modes together", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamResumable: true,
    streamMode: ["values", "events"],
  });

  expect(sanitized).toEqual({
    streamMode: ["values"],
  });
});
