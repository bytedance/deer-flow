export function extractTitleFromMarkdown(markdown: string) {
  if (markdown.startsWith("# ")) {
    let title = markdown.split("\n")[0]!.trim();
    if (title.startsWith("# ")) {
      title = title.slice(2).trim();
    }
    return title;
  }
  return undefined;
}
