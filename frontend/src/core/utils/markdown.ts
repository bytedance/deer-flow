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
  // closing sequence, not title text. Literal hashes (`# C#`) stay. Only
  // space/tab/CR may trail the closing sequence, so strip those by hand
  // instead of trimEnd(): trimEnd also removes non-ASCII whitespace, which
  // would turn a literal `### ` into a fake closing sequence.
  const title = firstLine
    .slice(headingPrefix[0].length)
    .replace(/[ \t\r]+$/, "")
    .replace(/(^|[ \t])#+$/, "")
    .trim();
  return title || undefined;
}
