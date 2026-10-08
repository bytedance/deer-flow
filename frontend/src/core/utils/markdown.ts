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
  const title = firstLine.slice(headingPrefix[0].length);
  // Scan backwards once: a whitespace-search regex can backtrack quadratically
  // on long fetched titles. Only ASCII spaces/tabs may follow closing hashes.
  let end = title.endsWith("\r") ? title.length - 1 : title.length;
  while (end > 0 && (title[end - 1] === " " || title[end - 1] === "\t")) {
    end--;
  }
  let hashStart = end;
  while (hashStart > 0 && title[hashStart - 1] === "#") {
    hashStart--;
  }
  if (
    hashStart < end &&
    (hashStart === 0 ||
      title[hashStart - 1] === " " ||
      title[hashStart - 1] === "\t")
  ) {
    return title.slice(0, hashStart).trim() || undefined;
  }
  return title.trim() || undefined;
}
