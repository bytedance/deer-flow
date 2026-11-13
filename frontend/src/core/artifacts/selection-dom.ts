import type { Root } from "hast";
import { SKIP, visit } from "unist-util-visit";

import { locateArtifactSelection } from "./selection";

// Runs after sanitization: authored attributes cannot impersonate source offsets.
export function rehypeArtifactSourceRanges({ source }: { source: string }) {
  return (tree: Root, file: { value: unknown }) => {
    // Preprocessing may change math, indentation or internal tags. In that
    // case offsets belong to the transformed text, not to the stored artifact.
    if (String(file.value) !== source) return;
    visit(tree, "element", (node) => {
      if (!/^(p|h[1-6]|li|pre|td|th|blockquote)$/.test(node.tagName)) return;
      const from = node.position?.start.offset;
      const to = node.position?.end.offset;
      if (from !== undefined && to !== undefined) {
        node.properties.dataArtifactFrom = from;
        node.properties.dataArtifactTo = to;
      }
    });
    visit(tree, (node, index, parent) => {
      // The renderer can replace code/math with its own DOM. Only plain text
      // nodes with a literal source span get an exact offset.
      if (
        node.type === "element" &&
        (node.tagName === "code" || node.tagName === "pre")
      )
        return SKIP;
      if (node.type !== "text" || index === undefined || !parent) return;
      const from = node.position?.start.offset;
      const to = node.position?.end.offset;
      if (
        from === undefined ||
        to === undefined ||
        !node.value ||
        source.slice(from, to) !== node.value
      )
        return;
      parent.children[index] = {
        type: "element",
        tagName: "span",
        properties: { dataArtifactTextFrom: from },
        children: [node],
      };
      return SKIP;
    });
  };
}

function exactTextRange(source: string, range: Range, text: string) {
  const node = range.startContainer;
  if (node.nodeType !== Node.TEXT_NODE || node !== range.endContainer)
    return null;
  const offset = node.parentElement?.dataset.artifactTextFrom;
  if (offset === undefined) return null;
  const start = Number(offset);
  const from = start + range.startOffset;
  const to = start + range.endOffset;
  return Number.isInteger(start) &&
    start >= 0 &&
    source.slice(from, to) === text
    ? { from, to }
    : null;
}

export function readArtifactSelection(container: HTMLElement, source: string) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1)
    return null;
  const range = selection.getRangeAt(0);
  if (
    !container.contains(range.startContainer) ||
    !container.contains(range.endContainer)
  )
    return null;
  const block = (node: Node) =>
    (node instanceof Element ? node : node.parentElement)?.closest<HTMLElement>(
      "[data-artifact-from][data-artifact-to]",
    );
  const start = block(range.startContainer);
  const end = block(range.endContainer);
  const text = selection.toString();
  const rect = range.getBoundingClientRect();
  const exact = exactTextRange(source, range, text);
  if (
    !start ||
    !end ||
    !container.contains(start) ||
    !container.contains(end)
  ) {
    return {
      text,
      range: exact ?? locateArtifactSelection(source, text),
      exact,
      rect,
    };
  }
  const from = Number(start.dataset.artifactFrom);
  const to = Number(end.dataset.artifactTo);
  if (
    !Number.isInteger(from) ||
    !Number.isInteger(to) ||
    from < 0 ||
    from >= to ||
    to > source.length
  )
    return null;
  return {
    text,
    range: { from, to },
    exact,
    rect,
  };
}
