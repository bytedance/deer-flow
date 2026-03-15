import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { StreamdownProps } from "streamdown";

import { rehypeSplitWordsIntoSpans } from "../rehype";

const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [...(defaultSchema.attributes?.code ?? []), "className"],
    span: [...(defaultSchema.attributes?.span ?? []), "className", "style"],
    div: [...(defaultSchema.attributes?.div ?? []), "className", "style"],
  },
};

export const streamdownPlugins = {
  remarkPlugins: [
    remarkGfm,
    [remarkMath, { singleDollarTextMath: true }],
  ] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    rehypeRaw,
    [rehypeSanitize, sanitizeSchema],
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

// Plugins for human messages - no autolink to prevent URL bleeding into adjacent text
export const humanMessagePlugins = {
  remarkPlugins: [
    // Use remark-gfm without autolink literals by not including it
    // Only include math support for human messages
    [remarkMath, { singleDollarTextMath: true }],
  ] as StreamdownProps["remarkPlugins"],
  rehypePlugins: [
    [rehypeKatex, { output: "html" }],
  ] as StreamdownProps["rehypePlugins"],
};
