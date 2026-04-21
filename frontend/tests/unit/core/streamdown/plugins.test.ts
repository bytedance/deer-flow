import rehypeRaw from "rehype-raw";
import { expect, test } from "vitest";

import { reasoningPlugins, streamdownPlugins } from "@/core/streamdown/plugins";

test("streamdownPlugins includes rehypeRaw", () => {
  expect(streamdownPlugins.rehypePlugins).toContain(rehypeRaw);
});

test("reasoningPlugins does not include rehypeRaw", () => {
  const flat = reasoningPlugins.rehypePlugins?.flat();
  expect(flat).not.toContain(rehypeRaw);
});
