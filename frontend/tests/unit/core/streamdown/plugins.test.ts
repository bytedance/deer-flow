import { expect, test } from "@rstest/core";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";

import {
  reasoningPlugins,
  streamdownPlugins,
  streamdownWordAnimation,
} from "@/core/streamdown/plugins";

test("shared streamdown configs disable single-tilde strikethrough", () => {
  const expectedGfmPlugin = [remarkGfm, { singleTilde: false }];

  expect(streamdownPlugins.remarkPlugins).toContainEqual(expectedGfmPlugin);
});

test("streaming word animation uses Streamdown's stable incremental animation", () => {
  expect(streamdownWordAnimation).toEqual({
    animation: "fadeIn",
    duration: 200,
    sep: "word",
  });
});

test("streamdownPlugins includes rehypeRaw", () => {
  expect(streamdownPlugins.rehypePlugins).toContain(rehypeRaw);
});

test("reasoningPlugins does not include rehypeRaw", () => {
  const flat = reasoningPlugins.rehypePlugins?.flat();
  expect(flat).not.toContain(rehypeRaw);
});
