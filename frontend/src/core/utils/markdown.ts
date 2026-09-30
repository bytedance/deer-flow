// Remove a whitespace-separated terminal hash run in linear time (CommonMark §4.2),
// avoiding quadratic backtracking on untrusted headings with long whitespace runs.
function stripAtxClosingHashes(raw: string): string {
  let end = raw.length;
  while (end > 0 && (raw[end - 1] === " " || raw[end - 1] === "\t")) {
    end--;
  }
  let hashStart = end;
  while (hashStart > 0 && raw[hashStart - 1] === "#") {
    hashStart--;
  }
  if (hashStart === end) {
    return raw.slice(0, end);
  }
  if (
    hashStart === 0 ||
    raw[hashStart - 1] === " " ||
    raw[hashStart - 1] === "\t"
  ) {
    while (
      hashStart > 0 &&
      (raw[hashStart - 1] === " " || raw[hashStart - 1] === "\t")
    ) {
      hashStart--;
    }
    return raw.slice(0, hashStart);
  }
  return raw.slice(0, end);
}

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
  const rawTitle = firstLine.slice(headingPrefix[0].length);
  return stripAtxClosingHashes(rawTitle).trim() || undefined;
}
