import { expect, test } from "vitest";

import { reasoningPlugins, streamdownPlugins } from "@/core/streamdown/plugins";

test("streamdownPlugins does not include rehypeRaw", () => {
  const flat = streamdownPlugins.rehypePlugins?.flat();
  expect(flat).toBeDefined();
  // rehypeRaw should not be present — it renders LLM-hallucinated HTML tags
  for (const entry of flat ?? []) {
    expect(typeof entry).not.toBe("function" as never);
  }
});

test("reasoningPlugins is the same as streamdownPlugins", () => {
  expect(reasoningPlugins).toBe(streamdownPlugins);
});
