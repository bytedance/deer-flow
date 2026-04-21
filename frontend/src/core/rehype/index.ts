import type { Element, Root } from "hast";
import { useMemo } from "react";
import { visit, EXIT } from "unist-util-visit";

const CJK_TEXT_RE =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;

const FADE_IN_CLASS = "animate-fade-in";

// Markdown block-level elements that receive the fade-in animation when the
// final (non-streaming) render is committed. The set mirrors the elements the
// previous per-word implementation targeted (see git history) so the visible
// effect scope is unchanged.
const FADE_IN_TAGS: ReadonlySet<string> = new Set([
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

function containsCjkText(node: Element): boolean {
  let found = false;
  visit(node, "text", (textNode) => {
    if (CJK_TEXT_RE.test(textNode.value)) {
      found = true;
      return EXIT;
    }
  });
  return found;
}

/**
 * Adds the ``animate-fade-in`` class to Markdown block elements so they fade
 * into view on final render. Equivalent to the previous per-word span wrapping
 * in terms of visible effect — the CSS keyframe is a plain opacity 0→1 over
 * 1.1s with no per-element delay, so fading each word individually and fading
 * the surrounding block produce the same on-screen result. Applying the class
 * to the block instead of every word eliminates the thousands of extra DOM
 * nodes the old implementation created on long responses.
 *
 * Blocks that contain any CJK text are intentionally left untouched, mirroring
 * the original behaviour where CJK text nodes were never wrapped.
 */
export function rehypeFadeInBlocks() {
  return (tree: Root) => {
    visit(tree, "element", (node: Element) => {
      if (!FADE_IN_TAGS.has(node.tagName) || !node.children) {
        return;
      }
      if (containsCjkText(node)) {
        return;
      }
      const properties = node.properties ?? (node.properties = {});
      const existing = properties.className;
      const classes = Array.isArray(existing)
        ? existing.map(String)
        : typeof existing === "string"
          ? existing.split(/\s+/).filter(Boolean)
          : [];
      if (!classes.includes(FADE_IN_CLASS)) {
        classes.push(FADE_IN_CLASS);
      }
      properties.className = classes;
    });
  };
}

export function useRehypeFadeInBlocks(enabled = true) {
  return useMemo(
    () => (enabled ? [rehypeFadeInBlocks] : []),
    [enabled],
  );
}
