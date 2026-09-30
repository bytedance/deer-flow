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
  // A trailing hash run preceded by a space or tab is CommonMark's optional
  // closing sequence, not title text. Literal hashes (`# C#`) stay.
  const title = firstLine
    .slice(headingPrefix[0].length)
    .trimEnd()
    .replace(/(^|[ \t])#+$/, "")
    .trim();
  return title || undefined;
}
