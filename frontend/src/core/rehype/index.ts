import type { Element, ElementContent, Root } from "hast";
import { useMemo } from "react";
import { visit } from "unist-util-visit";
import type { BuildVisitor } from "unist-util-visit";

const BLOCK_TAGS = new Set(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]);

const segmenter = new Intl.Segmenter("en", { granularity: "word" });

function splitTextIntoSpans(node: Element): void {
  const newChildren: Array<ElementContent> = [];
  node.children.forEach((child) => {
    if (child.type === "text") {
      const segments = segmenter.segment(child.value);
      const words = Array.from(segments)
        .map((segment) => segment.segment)
        .filter(Boolean);
      words.forEach((word: string) => {
        newChildren.push({
          type: "element",
          tagName: "span",
          properties: {
            className: "animate-fade-in",
          },
          children: [{ type: "text", value: word }],
        });
      });
    } else {
      newChildren.push(child);
    }
  });
  node.children = newChildren;
}

export function rehypeSplitWordsIntoSpans() {
  return (tree: Root) => {
    let lastBlock: Element | null = null;

    visit(tree, "element", ((node: Element) => {
      if (BLOCK_TAGS.has(node.tagName) && node.children) {
        lastBlock = node;
      }
    }) as BuildVisitor<Root, "element">);

    if (lastBlock) {
      splitTextIntoSpans(lastBlock);
    }
  };
}

export function useRehypeSplitWordsIntoSpans(enabled = true) {
  const rehypePlugins = useMemo(
    () => (enabled ? [rehypeSplitWordsIntoSpans] : []),
    [enabled],
  );
  return rehypePlugins;
}
