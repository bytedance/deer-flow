import { code } from "@streamdown/code";
import { mermaid } from "@streamdown/mermaid";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { StreamdownProps } from "streamdown";

const katexOptions = {
  output: "html",
  throwOnError: false,
  strict: false,
} as const;

const sharedRemarkPlugins = [
  [remarkGfm, { singleTilde: false }],
  [remarkMath, { singleDollarTextMath: true }],
] as StreamdownProps["remarkPlugins"];

export const streamdownRenderingPlugins = {
  code,
  mermaid,
} satisfies NonNullable<StreamdownProps["plugins"]>;

export const streamdownPlugins = {
  plugins: streamdownRenderingPlugins,
  remarkPlugins: sharedRemarkPlugins,
  rehypePlugins: [
    rehypeRaw,
    [rehypeKatex, katexOptions],
  ] as StreamdownProps["rehypePlugins"],
};

export const streamdownWordAnimation = {
  animation: "fadeIn",
  duration: 200,
  sep: "word",
} as const satisfies Exclude<StreamdownProps["animated"], boolean | undefined>;

export const streamdownPluginsWithoutRawHtml = {
  plugins: streamdownPlugins.plugins,
  remarkPlugins: streamdownPlugins.remarkPlugins,
  rehypePlugins: streamdownPlugins.rehypePlugins?.filter(
    (p) => p !== rehypeRaw,
  ) as StreamdownProps["rehypePlugins"],
};

// Plugins for reasoning/thinking content — derived from streamdownPlugins but without rehypeRaw,
// to prevent LLM-hallucinated HTML tags (e.g. <simd>) from being rendered as DOM elements.
export const reasoningPlugins = streamdownPluginsWithoutRawHtml;
