import type { Root } from "hast";
import { visit } from "unist-util-visit";

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
  };
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
  if (
    !start ||
    !end ||
    !container.contains(start) ||
    !container.contains(end)
  ) {
    const exact = locateArtifactSelection(source, text);
    return exact
      ? { text, range: exact, exact, rect: range.getBoundingClientRect() }
      : null;
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
    exact: locateArtifactSelection(source, text, from, to),
    rect: range.getBoundingClientRect(),
  };
}
