import { INDENTED_CODE_RE } from "@/core/streamdown/fences";

// Converter output can start with blank lines, and CommonMark allows up to three
// spaces before an ATX heading; a leading tab or four-space indent is a code block.
export function extractTitleFromMarkdown(markdown: string) {
  const firstLine = markdown.split("\n").find((line) => line.trim() !== "");
  if (firstLine === undefined || INDENTED_CODE_RE.test(firstLine)) {
    return undefined;
  }
  const heading = firstLine.trim();
  if (!heading.startsWith("# ")) {
    return undefined;
  }
  return heading.slice(2).trim() || undefined;
}
