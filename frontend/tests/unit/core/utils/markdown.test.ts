import { expect, test } from "@rstest/core";

import { extractTitleFromMarkdown } from "@/core/utils/markdown";

test("reads the title from a leading ATX heading", () => {
  expect(extractTitleFromMarkdown("# Real Title\n\nbody")).toBe("Real Title");
});

test.each([
  ["# Release Notes ###", "Release Notes"],
  ["# Release Notes ###   ", "Release Notes"],
  ["# Release Notes\t###\t", "Release Notes"],
  ["# Release Notes ###\r\nbody", "Release Notes"],
  ["# ###", undefined],
])("removes a closing ATX heading sequence from %j", (markdown, expected) => {
  expect(extractTitleFromMarkdown(markdown)).toBe(expected);
});

test.each([
  ["# C#", "C#"],
  ["# Release ### notes", "Release ### notes"],
  ["# Release ###x", "Release ###x"],
  ["# Release \\###", "Release \\###"],
])("preserves literal hashes in %j", (markdown, expected) => {
  expect(extractTitleFromMarkdown(markdown)).toBe(expected);
});

test.each(["\u00a0", "\u2003"])(
  "preserves literal hashes followed by non-ASCII whitespace %j",
  (whitespace) => {
    expect(extractTitleFromMarkdown(`# Release ###${whitespace}`)).toBe(
      "Release ###",
    );
    expect(extractTitleFromMarkdown(`# #${whitespace}\r\nbody`)).toBe("#");
  },
);

test("handles long whitespace and hash runs without changing literal content", () => {
  const spaces = " ".repeat(100_000);
  const hashes = "#".repeat(100_000);
  expect(extractTitleFromMarkdown(`# Title${spaces}#x`)).toBe(
    `Title${spaces}#x`,
  );
  expect(extractTitleFromMarkdown(`# Title${spaces}${hashes}\t\r\nbody`)).toBe(
    "Title",
  );
  expect(extractTitleFromMarkdown(`# ${hashes}x`)).toBe(`${hashes}x`);
  expect(extractTitleFromMarkdown(`# ${hashes}\t`)).toBeUndefined();
});

test("skips blank lines before the first heading", () => {
  expect(extractTitleFromMarkdown("\n# Real Title\n\nbody")).toBe("Real Title");
  expect(extractTitleFromMarkdown("  \n\n# Real Title")).toBe("Real Title");
});

test("accepts the up-to-three-space indentation CommonMark allows", () => {
  expect(extractTitleFromMarkdown("   # Real Title")).toBe("Real Title");
});

test("ignores an indented code block that starts with a hash", () => {
  expect(extractTitleFromMarkdown("    # Not A Title")).toBeUndefined();
  expect(extractTitleFromMarkdown("\t# Not A Title")).toBeUndefined();
});

test.each([" \t", "  \t", "   \t"])(
  "does not treat mixed indentation %j as a heading",
  (indent) => {
    expect(
      extractTitleFromMarkdown(`${indent}# Code comment\n# Later heading`),
    ).toBeUndefined();
    expect(
      extractTitleFromMarkdown(`\n  \n${indent}# Code comment`),
    ).toBeUndefined();
  },
);

test.each(["", " ", "  ", "   "])(
  "accepts a heading with %j indentation and CRLF line endings",
  (indent) => {
    expect(extractTitleFromMarkdown(`\r\n${indent}# Real Title\r\nbody`)).toBe(
      "Real Title",
    );
  },
);

test("ignores headings that are not level 1", () => {
  expect(extractTitleFromMarkdown("## Section")).toBeUndefined();
  expect(extractTitleFromMarkdown("#NoSpace")).toBeUndefined();
});

test("does not report an empty heading as a title", () => {
  expect(extractTitleFromMarkdown("# \n\nbody")).toBeUndefined();
  expect(extractTitleFromMarkdown("#")).toBeUndefined();
});

test("returns undefined when the document has no content", () => {
  expect(extractTitleFromMarkdown("")).toBeUndefined();
  expect(extractTitleFromMarkdown("   \n  ")).toBeUndefined();
  expect(
    extractTitleFromMarkdown("Plain text with no heading"),
  ).toBeUndefined();
});
