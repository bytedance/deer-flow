// Converter output can start with blank lines, and CommonMark allows up to three
// literal spaces before an ATX heading. Do not trim code indentation into a title.
export function extractTitleFromMarkdown(markdown: string) {
  const firstLine = markdown.split("\n").find((line) => line.trim() !== "");
  if (firstLine === undefined) {
    return undefined;
  }
  const withoutClosing = stripAtxClosingSequence(firstLine);
  const headingPrefix = /^ {0,3}# /.exec(withoutClosing);
  if (!headingPrefix) {
    return undefined;
  }
  return withoutClosing.slice(headingPrefix[0].length).trim() || undefined;
}

// A closing run of #s is heading syntax when a space or tab precedes it and
// only spaces, tabs or the CRLF tail follow it (CommonMark ATX headings).
// Stripping it from the raw line also collapses "# ###" - content that is
// nothing but the closing sequence - to no title.
function stripAtxClosingSequence(line: string) {
  // A suffix regex such as /[ \t]+#+[ \t]*\r?$/ retries the whitespace run at
  // every start position and goes quadratic on titles like "# t" plus a long
  // run of spaces plus trailing text, so scan backwards from the end instead.
  let end = line.length;
  if (line[end - 1] === "\r") {
    end -= 1;
  }
  while (end > 0 && (line[end - 1] === " " || line[end - 1] === "\t")) {
    end -= 1;
  }
  let hashesEnd = end;
  while (hashesEnd > 0 && line[hashesEnd - 1] === "#") {
    hashesEnd -= 1;
  }
  if (
    hashesEnd === end ||
    hashesEnd === 0 ||
    (line[hashesEnd - 1] !== " " && line[hashesEnd - 1] !== "\t")
  ) {
    return line;
  }
  let contentEnd = hashesEnd;
  while (
    contentEnd > 0 &&
    (line[contentEnd - 1] === " " || line[contentEnd - 1] === "\t")
  ) {
    contentEnd -= 1;
  }
  return line.slice(0, contentEnd);
}
