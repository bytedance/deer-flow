// Converter output can start with blank lines, and CommonMark allows up to three
// literal spaces before an ATX heading. Do not trim code indentation into a title.
export function extractTitleFromMarkdown(markdown: string) {
  const firstLine = markdown.split("\n").find((line) => line.trim() !== "");
  if (firstLine === undefined) {
    return undefined;
  }
  const headingPrefix = /^ {0,3}# /.exec(firstLine);
  if (!headingPrefix) {
    return undefined;
  }
  return firstLine.slice(headingPrefix[0].length).trim() || undefined;
}
