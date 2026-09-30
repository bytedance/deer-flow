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
  // CommonMark §4.2: ATX headings allow an optional closing sequence of '#' characters
  // preceded by whitespace (spaces or tabs) and followed only by spaces or tabs.
  const rawTitle = firstLine.slice(headingPrefix[0].length);
  const strippedTitle = rawTitle.replace(/[ \t]+#+[ \t]*$/, "");
  return strippedTitle.trim() || undefined;
}
