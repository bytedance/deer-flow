// Converter output can start with blank lines, and CommonMark allows up to three
// literal spaces before an ATX heading. Do not trim code indentation into a title.
export function extractTitleFromMarkdown(markdown: string) {
  const firstLine = markdown.split("\n").find((line) => line.trim() !== "");
  if (firstLine === undefined) {
    return undefined;
  }
  // A closing run of #s is heading syntax when a space or tab precedes it and
  // only spaces, tabs or the CRLF tail follow it (CommonMark ATX headings).
  // Stripping it from the raw line also collapses "# ###" - content that is
  // nothing but the closing sequence - to no title.
  const withoutClosing = firstLine.replace(/[ \t]+#+[ \t]*\r?$/, "");
  const headingPrefix = /^ {0,3}# /.exec(withoutClosing);
  if (!headingPrefix) {
    return undefined;
  }
  return withoutClosing.slice(headingPrefix[0].length).trim() || undefined;
}
