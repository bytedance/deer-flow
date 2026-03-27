import type { Element, ElementContent, Root } from "hast";
import { useMemo } from "react";
import { visit } from "unist-util-visit";
import type { BuildVisitor } from "unist-util-visit";

const ANIMATED_TAG_NAMES = new Set([
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "li",
  "strong",
]);
const URL_LIKE_RE = /(?:https?:\/\/|www\.)\S+/i;
const PATH_LIKE_RE = /(?:^|[\s(])(?:\/(?:[\w.-]+\/?)+|[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]*)/;
const COMMAND_LIKE_RE = /\b(?:python|bash|sh|zsh|uv|pnpm|npm|node|git|cd|ls|cp|mv|mkdir|rm|export|cat|echo|chmod)\b/i;
const CLI_TOKEN_RE = /(?:--[\w-]+|\b[\w.-]+=\S+|`{1,3}|\/mnt\/)/;
const HAN_TEXT_RE = /\p{Script=Han}/gu;
const ASCII_TEXT_RE = /[A-Za-z0-9]/g;
const segmenter = new Intl.Segmenter("zh", { granularity: "word" });

export function shouldSplitAnimatedText(value: string): boolean {
  const text = value.trim();
  if (!text) {
    return false;
  }

  if (
    URL_LIKE_RE.test(text) ||
    PATH_LIKE_RE.test(text) ||
    COMMAND_LIKE_RE.test(text) ||
    CLI_TOKEN_RE.test(text)
  ) {
    return false;
  }

  const hanCount = (text.match(HAN_TEXT_RE) ?? []).length;
  if (hanCount === 0) {
    return false;
  }

  const asciiCount = (text.match(ASCII_TEXT_RE) ?? []).length;
  return hanCount >= asciiCount;
}

export function rehypeSplitWordsIntoSpans() {
  return (tree: Root) => {
    visit(tree, "element", ((node: Element) => {
      if (!ANIMATED_TAG_NAMES.has(node.tagName) || !node.children) {
        return;
      }

      const newChildren: Array<ElementContent> = [];
      node.children.forEach((child) => {
        if (child.type !== "text" || !shouldSplitAnimatedText(child.value)) {
          newChildren.push(child);
          return;
        }

        const words = Array.from(segmenter.segment(child.value))
          .map((segment) => segment.segment)
          .filter(Boolean);

        if (words.length <= 1) {
          newChildren.push(child);
          return;
        }

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
      });
      node.children = newChildren;
    }) as BuildVisitor<Root, "element">);
  };
}

export function useRehypeSplitWordsIntoSpans(enabled = true) {
  const rehypePlugins = useMemo(
    () => (enabled ? [rehypeSplitWordsIntoSpans] : []),
    [enabled],
  );
  return rehypePlugins;
}
