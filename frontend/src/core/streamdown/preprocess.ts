import { normalizeMermaidMarkdown } from "./mermaid";

export function preprocessStreamdownMarkdown(markdown: string): string {
  return normalizeMermaidMarkdown(markdown);
}
