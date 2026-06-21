import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { StreamdownProps } from "streamdown";

import { rehypeSplitWordsIntoSpans } from "../rehype";

export const streamdownPlugins = {
  remarkPlugins: [
    remarkGfm,
    [remarkMath, { singleDollarTextMath: true }],
  ] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    rehypeRaw,
    [rehypeKatex, { output: "html" }],
  ] as StreamdownProps["rehypePlugins"],
};

export const streamdownPluginsWithWordAnimation = {
  remarkPlugins: [
    remarkGfm,
    [remarkMath, { singleDollarTextMath: true }],
  ] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    [rehypeKatex, { output: "html" }],
    rehypeSplitWordsIntoSpans,
  ] as StreamdownProps["rehypePlugins"],
};

// Plugins for reasoning/thinking content — derived from streamdownPlugins but without rehypeRaw,
// to prevent LLM-hallucinated HTML tags (e.g. <simd>) from being rendered as DOM elements.
export const reasoningPlugins = {
  remarkPlugins: streamdownPlugins.remarkPlugins,
  rehypePlugins: streamdownPlugins.rehypePlugins?.filter(
    (p) => p !== rehypeRaw,
  ) as StreamdownProps["rehypePlugins"],
};
