import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { StreamdownProps } from "streamdown";

import { rehypeSplitWordsIntoSpans } from "../rehype";

const katexOptions = {
  output: "html",
  throwOnError: false,
  strict: false,
} as const;

const sharedRemarkPlugins = [
  [remarkGfm, { singleTilde: false }],
  [remarkMath, { singleDollarTextMath: true }],
] as StreamdownProps["remarkPlugins"];

export const streamdownPlugins = {
  remarkPlugins: sharedRemarkPlugins,
  rehypePlugins: [
    rehypeRaw,
    [rehypeKatex, katexOptions],
  ] as StreamdownProps["rehypePlugins"],
};

export const streamdownPluginsWithWordAnimation = {
  remarkPlugins: sharedRemarkPlugins,
  rehypePlugins: [
    [rehypeKatex, katexOptions],
    rehypeSplitWordsIntoSpans,
  ] as StreamdownProps["rehypePlugins"],
};

export const streamdownPluginsWithoutRawHtml = {
  remarkPlugins: streamdownPlugins.remarkPlugins,
  rehypePlugins: streamdownPlugins.rehypePlugins?.filter(
    (p) => p !== rehypeRaw,
  ) as StreamdownProps["rehypePlugins"],
};

// Plugins for reasoning/thinking content — derived from streamdownPlugins but without rehypeRaw,
// to prevent LLM-hallucinated HTML tags (e.g. <simd>) from being rendered as DOM elements.
export const reasoningPlugins = streamdownPluginsWithoutRawHtml;
