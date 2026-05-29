import { normalizeMermaidMarkdown } from "./mermaid";

const MERMAID_BLOCK_HINT_RE = /mermaid/i;

export function preprocessStreamdownMarkdown(markdown: string): string {
  if (!MERMAID_BLOCK_HINT_RE.test(markdown) || !markdown.includes("-.->")) {
    return markdown;
  }

  return normalizeMermaidMarkdown(markdown);
}
