import type { ReactElement, ReactNode } from "react";

const BLOCK_LEVEL_TAGS = new Set([
  "div",
  "section",
  "article",
  "header",
  "footer",
  "main",
  "aside",
  "nav",
  "figure",
  "figcaption",
  "table",
  "thead",
  "tbody",
  "tfoot",
  "tr",
  "ol",
  "ul",
  "li",
  "dl",
  "dt",
  "dd",
  "blockquote",
  "pre",
  "hr",
  "form",
  "canvas",
  "video",
  "audio",
  "iframe",
  "object",
]);

export function isBlockLevelChild(node: ReactNode): boolean {
  if (!node || typeof node !== "object") {
    return false;
  }

  const element = node as ReactElement<Record<string, unknown>>;
  if (element.type === "div") {
    return true;
  }

  if (typeof element.type === "string" && BLOCK_LEVEL_TAGS.has(element.type)) {
    return true;
  }

  const props = element.props;
  return !!props && typeof props === "object" && "data-code-block-container" in props;
}

export function hasBlockLevelChildren(children: ReactNode): boolean {
  if (Array.isArray(children)) {
    return children.some(isBlockLevelChild);
  }
  return isBlockLevelChild(children);
}

export function filterPresentChildren(children: ReactNode): ReactNode[] {
  const normalizedChildren = Array.isArray(children) ? children : [children];
  return normalizedChildren.filter((child) => child !== null && child !== undefined && child !== "");
}
