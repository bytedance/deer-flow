import { expect, test } from "@rstest/core";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";

import {
  reasoningPlugins,
  streamdownPlugins,
  streamdownPluginsWithWordAnimation,
} from "@/core/streamdown/plugins";

test("shared streamdown configs disable single-tilde strikethrough", () => {
  const expectedGfmPlugin = [remarkGfm, { singleTilde: false }];

  expect(streamdownPlugins.remarkPlugins).toContainEqual(expectedGfmPlugin);
  expect(streamdownPluginsWithWordAnimation.remarkPlugins).toContainEqual(
    expectedGfmPlugin,
  );
});

test("streamdownPlugins includes rehypeRaw", () => {
  expect(streamdownPlugins.rehypePlugins).toContain(rehypeRaw);
});

test("reasoningPlugins does not include rehypeRaw", () => {
  const flat = reasoningPlugins.rehypePlugins?.flat();
  expect(flat).not.toContain(rehypeRaw);
});
