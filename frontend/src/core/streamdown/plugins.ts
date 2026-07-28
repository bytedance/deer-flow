import { code } from "@streamdown/code";
import { mermaid } from "@streamdown/mermaid";
import type { Root } from "hast";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { StreamdownProps } from "streamdown";
import { visit } from "unist-util-visit";

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

export const streamdownSmoothStreamingAnimation = {
  ...streamdownWordAnimation,
  // Streamdown defaults to 40ms per new word. A large chunk can therefore
  // delay later list-item text by seconds while its native marker is already
  // visible. Smooth content reveal owns the pacing here, so start every new
  // word's fade together with its surrounding marker.
  stagger: 0,
} as const satisfies Exclude<StreamdownProps["animated"], boolean | undefined>;

/**
 * Keeps native list markers in step with Streamdown's word reveal.
 *
 * A trailing `2.` or `-` is parsed as an empty list item while content is
 * streaming. Hide that transient item, then mark it for a matching marker
 * animation as soon as its first child arrives. Keep mid-list empty items in
 * the box tree so ordered-list counters never renumber later items.
 */
export function rehypeStreamingListItems() {
  return (tree: Root) => {
    visit(tree, "element", (node, index, parent) => {
      if (node.tagName !== "li") {
        return;
      }

      if (node.children.length === 0) {
        const isTrailingListItem =
          index !== undefined &&
          parent?.type === "element" &&
          (parent.tagName === "ol" || parent.tagName === "ul") &&
          !parent.children
            .slice(index + 1)
            .some(
              (sibling) =>
                sibling.type === "element" && sibling.tagName === "li",
            );
        if (isTrailingListItem) {
          node.properties.hidden = true;
        }
        return;
      }

      node.properties["data-streaming-list-item"] = "true";
    });
  };
}

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
